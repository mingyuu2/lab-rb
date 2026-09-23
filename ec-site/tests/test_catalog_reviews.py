"""Regression checks: python -m unittest discover -s tests -v (from ec-site)."""
import importlib
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import db
from products import get_categories, get_product, get_products


class CatalogTests(unittest.TestCase):
    def test_catalog_assets_and_original_identifiers(self):
        products = get_products()
        self.assertEqual(len(products), 100)
        self.assertEqual({p['id'] for p in products}, set(range(1, 101)))
        self.assertEqual(len({p['name'] for p in products}), 100)
        self.assertEqual(len(get_categories()), 6)
        self.assertEqual(get_product(1)['name'], 'ワイヤレスイヤホン')
        self.assertEqual(get_product(1)['price'], 9900)
        self.assertEqual(get_product(30)['name'], 'カラー蛍光ペンセット')
        base = Path(__file__).resolve().parents[1]
        for product in products:
            with self.subTest(product=product['id']):
                self.assertGreater(product['price'], 0)
                self.assertEqual(product['image_url'], f"http://ec-site/static/img/products/{product['image']}")
                ET.parse(base / 'static' / 'img' / 'products' / product['image'])

    def test_search_normalizes_width_case_and_whitespace(self):
        expected = get_products(query='bluetooth')
        self.assertTrue(expected)
        self.assertEqual(get_products(query='  ＢＬＵＥＴＯＯＴＨ　'), expected)
        self.assertEqual(get_products(query='\t　 '), get_products())

    def test_search_includes_descriptions_and_categories(self):
        self.assertIn(1, [p['id'] for p in get_products(query='ノイズキャンセリング')])
        self.assertEqual(get_products(query='電子機器'), get_products('電子機器'))
        self.assertEqual(get_products(query='ない商品xyz'), [])

    def test_search_terms_and_category_intersect(self):
        products = get_products('電子機器', 'USB-C 充電')
        self.assertTrue(products)
        self.assertIn(34, [p['id'] for p in products])
        self.assertEqual(get_products('ビューティー', 'USB-C'), [])


class StorefrontTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path_patch = patch.object(db, 'DB_PATH', Path(self.temp.name) / 'test.db')
        self.path_patch.start()
        self.addCleanup(self.path_patch.stop)
        self.module = importlib.import_module('app')
        db.init_db()
        self.app = self.module.app
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()
        with self.app.app_context():
            connection = db.get_db()
            connection.execute("INSERT INTO users (email, password_hash, nickname) VALUES ('test@example.test', 'test', 'テスト')")
            connection.execute("INSERT INTO users (email, password_hash, nickname) VALUES ('other@example.test', 'test', '別ユーザー')")
            connection.commit()
        with self.client.session_transaction() as session:
            session['user_id'] = 1
            session['nickname'] = 'テスト'

    def rows(self):
        with self.app.app_context():
            return db.get_db().execute('SELECT * FROM reviews ORDER BY id').fetchall()

    def post_review(self, **values):
        return self.client.post('/product/1/review', data={'content': 'レビュー', **values})

    def test_all_product_details_render(self):
        for product in get_products():
            with self.subTest(product=product['id']):
                response = self.client.get(f"/product/{product['id']}")
                self.assertEqual(response.status_code, 200)
                self.assertIn(product['name'], response.get_data(as_text=True))
        self.assertEqual(self.client.get('/product/101').status_code, 404)

    def test_search_ui_preserves_filters_and_escapes_queries(self):
        from html.parser import HTMLParser
        class Elements(HTMLParser):
            def __init__(self, html):
                super().__init__()
                self.links = []
                self.inputs = []
                self.feed(html)
            def handle_starttag(self, tag, attrs):
                if tag == 'a':
                    self.links.append(dict(attrs))
                if tag == 'input':
                    self.inputs.append(dict(attrs))
        response = self.client.get('/', query_string={'q': 'USB-C', 'category': '電子機器'})
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        parsed = Elements(html)
        self.assertIn('検索結果', html)
        self.assertTrue(any(i.get('name') == 'q' and i.get('value') == 'USB-C' for i in parsed.inputs))
        self.assertTrue(any(i.get('name') == 'category' and i.get('value') == '電子機器' for i in parsed.inputs))
        category_links = [a['href'] for a in parsed.links if 'category-pill' in a.get('class', '')]
        self.assertEqual(len(category_links), 7)
        self.assertTrue(all('q=USB-C' in href for href in category_links))
        empty = self.client.get('/', query_string={'q': '<script>alert(1)</script>'}).get_data(as_text=True)
        self.assertIn('条件に合う商品が見つかりません', empty)
        self.assertNotIn('<script>alert(1)</script>', empty)
        self.assertIn('&lt;script&gt;', empty)

    def test_ratings_and_legacy_posts_average_only_rated_reviews(self):
        for rating in ['', '1', '2', '3', '4', '5']:
            self.assertEqual(self.post_review(rating=rating).status_code, 302)
        self.assertEqual(self.post_review(content='{{ product.name }}').status_code, 302)
        self.assertEqual([r['rating'] for r in self.rows()], [None, 1, 2, 3, 4, 5, None])
        html = self.client.get('/product/1').get_data(as_text=True)
        self.assertIn('3.0', html)
        self.assertIn('5件の評価に基づく平均', html)
        self.assertIn('評価なし', html)
        self.assertNotIn('{{ product.name }}</div>', html)
        self.assertIn('ワイヤレスイヤホン</div>', html)
        self.assertIn('aria-label="5点中5.0点"', html)

    def test_invalid_rating_is_rejected_without_losing_content(self):
        for rating in ['0', '6', '-1', '2.5', 'hello', '99999999999999999']:
            with self.subTest(rating=rating):
                response = self.post_review(rating=rating, content='書きかけのレビュー <b>保留</b>')
                self.assertEqual(response.status_code, 400)
                html = response.get_data(as_text=True)
                self.assertIn('星の数は1〜5から選択', html)
                self.assertIn('書きかけのレビュー &lt;b&gt;保留&lt;/b&gt;', html)
        self.assertEqual(self.rows(), [])

    def test_empty_review_does_not_create_a_rating(self):
        self.post_review(content='  ', rating='5')
        self.assertEqual(self.rows(), [])

    def test_auth_ownership_and_average_after_delete(self):
        anonymous = self.app.test_client()
        self.assertEqual(anonymous.post('/product/1/review', data={'content': 'no', 'rating': '5'}).status_code, 302)
        self.post_review(rating='1')
        self.post_review(rating='5')
        other = self.app.test_client()
        with other.session_transaction() as session:
            session['user_id'] = 2
        other.post('/product/1/review/1/delete')
        self.assertEqual(len(self.rows()), 2)
        other_html = other.get('/product/1').get_data(as_text=True)
        self.assertNotIn('/review/1/delete', other_html)
        self.client.post('/product/1/review/1/delete')
        html = self.client.get('/product/1').get_data(as_text=True)
        self.assertIn('5.0', html)
        self.assertIn('1件の評価に基づく平均', html)
        self.client.post('/product/1/review/2/delete')
        self.assertIn('まだ評価はありません', self.client.get('/product/1').get_data(as_text=True))

    def test_new_products_use_existing_cart_checkout_history(self):
        self.client.post('/cart/add', data={'product_id': '100', 'qty': '2'})
        self.assertIn('2,200', self.client.get('/cart').get_data(as_text=True))
        response = self.client.post('/checkout', data={'name': 'テスト', 'address': 'テスト住所'})
        self.assertEqual(response.status_code, 200)
        history = self.client.get('/orders').get_data(as_text=True)
        self.assertIn('パステル蛍光ペン5色セット', history)
        self.assertIn('2,200', history)

    def test_legacy_database_migration_preserves_data_and_is_repeatable(self):
        legacy_path = Path(self.temp.name) / 'legacy.db'
        with sqlite3.connect(legacy_path) as connection:
            schema = db.SCHEMA_PATH.read_text().replace('    rating INTEGER CHECK (rating BETWEEN 1 AND 5),\n', '')
            connection.executescript(schema)
            connection.execute("INSERT INTO users (id, email, password_hash) VALUES (42, 'legacy@example.test', 'original-hash')")
            connection.execute("INSERT INTO reviews (id, product_id, user_id, content) VALUES (7, 1, 42, '古いレビュー')")
            connection.execute("INSERT INTO orders (id, user_id, recipient_name, address, total) VALUES (9, 42, '名前', '住所', 9900)")
        with patch.object(db, 'DB_PATH', legacy_path):
            db.init_db()
            db.init_db()
            with sqlite3.connect(legacy_path) as connection:
                self.assertEqual(connection.execute('SELECT content, rating FROM reviews WHERE id=7').fetchone(), ('古いレビュー', None))
                self.assertEqual(connection.execute('SELECT password_hash FROM users WHERE id=42').fetchone()[0], 'original-hash')
                self.assertEqual(connection.execute('SELECT total FROM orders WHERE id=9').fetchone()[0], 9900)
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute('UPDATE reviews SET rating=9 WHERE id=7')


if __name__ == '__main__':
    unittest.main()
