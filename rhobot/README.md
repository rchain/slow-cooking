# Setup

 1. Register new application at https://github.com/organizations/rchain/settings/applications

Authorization callback URL is `/authorize`.

 2. Add DNS CNAME
 3. Configure nginx proxy_pass to the internal gcloud DNS name of a machine running rhobot

```
server {
    server_name NAME;

    location / {
        proxy_pass ADDRESS:PORT;

        proxy_set_header  Host               $host;
        proxy_set_header  X-Real-IP          $remote_addr;
        proxy_set_header  X-Forwarded-For    $proxy_add_x_forwarded_for;
        proxy_set_header  X-Forwarded-Proto  $scheme;
    }
}
```
