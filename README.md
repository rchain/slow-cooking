# Usage
## Drone instance deployment

Install python on the target machine so that Ansible can take over: `apt
update && apt install python`.  Within the `deployment` directory, execute:

    $ ansible-playbook --inventory=SSH_HOST, --user=SSH_USER --private-key=SSH_PRIVATE_KEY --vault-password-file=PASSWORD_FILE --verbose drone.yml

## Rhobot deployment

Withing the `deployment` directory, execute:

    $ ansible-playbook --inventory=SSH_HOST, --user=SSH_USER --private-key=SSH_PRIVATE_KEY --vault-password-file=PASSWORD_FILE --verbose rhobot.yml

Apart from deploying code and configuring a OS process, Rhobot also needs some
configuration of the GitHub organization.

 * Register new application at
   https://github.com/organizations/rchain/settings/applications; the
   authorization callback URL is `/authorize`.

 * Add DNS CNAME pointing to a publicly accessible cloud instance
 * Configure nginx proxy_pass to the internal gcloud DNS name of a machine
   running rhobot.  Below is a configuration file template (fill in `NAME`,
   `ADDRESS`, and `PORT):

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
