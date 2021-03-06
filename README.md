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

### Rhobot for trigerring perf harness builds from GitHub pull requests

1) Enable `Issue comments` events at https://github.com/rchain/rchain/settings/hooks/

This may be confusing as `issue_comments` events are trigerred whenever a
comment is being made in a pull request.

2) [Generate a personal access token](https://help.github.com/en/articles/creating-a-personal-access-token-for-the-command-line)

The token needs to have the 'repo' permission enabled.  This is required for
checking whether a pull request author is a collaborator.

Use a separate GitHub account preferably, like https://github.com/rchain-service.
