# Usage

Install python on the target machine so that Ansible can take over: `apt update && apt install python`

    $ cd deployment
    $ ansible-playbook --inventory=SSH_HOST, --user=SSH_USER --private-key=SSH_PRIVATE_KEY --vault-password-file=PASSWORD_FILE --verbose site.yml
