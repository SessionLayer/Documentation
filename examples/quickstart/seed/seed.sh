#!/bin/sh
# One-shot quickstart provisioning for the pieces that have no public API
# surface (everything else in the guide goes through the real REST API):
#
#   1. the internal mTLS CA certificate  -> /state/ca.pem        (Gateway trust anchor)
#   2. the session CA public key         -> /state/session_ca.pub (node TrustedUserCAKeys)
#   3. a single-use Gateway enrollment token + the rendered Gateway config
#   4. the `quickstart-admin` service account + its dev-only client secret
#      (the first-admin bootstrap claim in the guide is what makes it an admin)
#   5. a demo customer recording key pair: the PUBLIC half goes to the Control
#      Plane; the private half stays on the dedicated /keys volume (mounted
#      only here and into the decrypt tool) and never leaves this stack
#
# Idempotent: safe to re-run on every `docker compose up`.
set -eu

STATE=/state
export PGPASSWORD=sessionlayer
psql_q() { psql -h postgres -U sessionlayer -d sessionlayer -tA -v ON_ERROR_STOP=1 -c "$1"; }
sha_hex() { printf %s "$1" | sha256sum | cut -d' ' -f1; }

log() { echo "seed: $*"; }

# /v1/healthz goes green while the CP's cold-start provisioning (CAs +
# operator_settings) may still be running; gate on the rows actually existing.
log "waiting for Control Plane cold-start provisioning (CAs + operator settings)"
deadline=$(( $(date +%s) + 300 ))
while :; do
	n=$(psql_q "SELECT
	  (SELECT count(*) FROM runtime.ca_key_material k JOIN config.ca_config c ON c.id=k.ca_config_id
	     WHERE c.ca_kind='mtls' AND k.ca_certificate IS NOT NULL)
	+ (SELECT count(*) FROM runtime.ca_key_material k JOIN config.ca_config c ON c.id=k.ca_config_id
	     WHERE c.ca_kind='session' AND c.rotation_state='active' AND k.public_key IS NOT NULL)
	+ (SELECT count(*) FROM runtime.ca_key_material k JOIN config.ca_config c ON c.id=k.ca_config_id
	     WHERE c.ca_kind='host' AND c.rotation_state='active' AND k.public_key IS NOT NULL)
	+ (SELECT count(*) FROM config.operator_settings WHERE singleton=true)" 2>/dev/null || echo 0)
	[ "$n" = "4" ] && break
	[ "$(date +%s)" -lt "$deadline" ] || { echo "seed: FAIL: Control Plane provisioning incomplete" >&2; exit 1; }
	sleep 2
done

log "extracting the internal mTLS CA -> /state/ca.pem"
{
	echo '-----BEGIN CERTIFICATE-----'
	psql_q "SELECT encode(k.ca_certificate,'base64') FROM runtime.ca_key_material k
	        JOIN config.ca_config c ON c.id=k.ca_config_id WHERE c.ca_kind='mtls'" | tr -d '\n' | fold -w64
	echo
	echo '-----END CERTIFICATE-----'
} > "$STATE/ca.pem"
openssl x509 -in "$STATE/ca.pem" -noout -subject >/dev/null

log "extracting the session CA -> /state/session_ca.pub (node TrustedUserCAKeys line)"
{
	echo '-----BEGIN PUBLIC KEY-----'
	psql_q "SELECT encode(k.public_key,'base64') FROM runtime.ca_key_material k
	        JOIN config.ca_config c ON c.id=k.ca_config_id
	        WHERE c.ca_kind='session' AND c.rotation_state='active'" | tr -d '\n' | fold -w64
	echo
	echo '-----END PUBLIC KEY-----'
} > "$STATE/session_ca_spki.pem"
ssh-keygen -i -m PKCS8 -f "$STATE/session_ca_spki.pem" > "$STATE/session_ca.pub"

log "extracting the host CA -> /state/host_ca.pub (client @cert-authority anchor)"
{
	echo '-----BEGIN PUBLIC KEY-----'
	psql_q "SELECT encode(k.public_key,'base64') FROM runtime.ca_key_material k
	        JOIN config.ca_config c ON c.id=k.ca_config_id
	        WHERE c.ca_kind='host' AND c.rotation_state='active'" | tr -d '\n' | fold -w64
	echo
	echo '-----END PUBLIC KEY-----'
} > "$STATE/host_ca_spki.pem"
ssh-keygen -i -m PKCS8 -f "$STATE/host_ca_spki.pem" > "$STATE/host_ca.pub"

if [ ! -f "$STATE/gateway.json" ]; then
	log "minting a single-use Gateway enrollment token + rendering /state/gateway.json"
	token="qs-$(head -c16 /dev/urandom | od -An -tx1 | tr -d ' \n')"
	psql_q "INSERT INTO runtime.gateway_enrollment_token(id,token_hash,gateway_name,single_use,expires_at,created_by)
	        VALUES (gen_random_uuid(),'$(sha_hex "$token")','gw-quickstart',true,now()+interval '2 hours','quickstart-seed')" >/dev/null
	# require_https=false is DEV-ONLY: this stack's WORM store is an in-network
	# plain-HTTP MinIO; the product default is true — keep it in production
	# (docs/reference/config-gateway.md). host_key_path persists the outer SSH
	# host key in the data volume so clients can verify a stable front door.
	cat > "$STATE/gateway.json" <<EOF
{
  "cp_mtls_endpoint": "https://controlplane:9443",
  "data_dir": "/var/lib/sessionlayer-gateway",
  "bootstrap": {
    "enrollment_token": "$token",
    "ca_cert_path": "/state/ca.pem",
    "gateway_name": "gw-quickstart",
    "server_name": "controlplane"
  },
  "ssh": {
    "listen_addr": "0.0.0.0:2222",
    "host_key_path": "/var/lib/sessionlayer-gateway/ssh_host_key",
    "node_dns_suffixes": ["nodes.example.com"],
    "proxy_jump": {
      "enabled": true
    },
    "recorder": {
      "require_https": false
    }
  },
  "ha": {
    "mode": "single_instance"
  }
}
EOF
fi

log "creating the quickstart-admin service account (dev-only client secret)"
admin_hash="$(sha_hex quickstart-admin-dev-secret)"
psql -h postgres -U sessionlayer -d sessionlayer -v ON_ERROR_STOP=1 -q <<SQL
INSERT INTO config.service_account(id,name,description,auth_method,origin)
VALUES (gen_random_uuid(),'quickstart-admin','quickstart evaluation admin','client_secret','default')
ON CONFLICT (name) DO NOTHING;
INSERT INTO runtime.service_account_credential(id,service_account_id,service_account_name,credential_type,secret_hash,status,issued_at)
SELECT gen_random_uuid(), sa.id, sa.name, 'client_secret', '$admin_hash', 'active', now()
FROM config.service_account sa WHERE sa.name='quickstart-admin'
  AND NOT EXISTS (SELECT 1 FROM runtime.service_account_credential c WHERE c.service_account_name='quickstart-admin');
SQL

# The private half lives on its own volume (/keys), mounted only here and into
# the decrypt tool — never into the recorded node, the client, or the Gateway.
if [ ! -f /keys/customer_key.pem ]; then
	log "generating the demo customer recording key (public half -> Control Plane)"
	openssl ecparam -name prime256v1 -genkey -noout -out /keys/customer_key.pem 2>/dev/null
	chmod 600 /keys/customer_key.pem
fi
pub_b64=$(openssl ec -in /keys/customer_key.pem -pubout -outform DER 2>/dev/null | base64 | tr -d '\n')
psql_q "UPDATE config.operator_settings
        SET recording_customer_public_key = decode('$pub_b64','base64'),
            recording_key_seal_algorithm = 'ecies_p256',
            default_worm_mode = 'compliance'
        WHERE singleton = true AND recording_customer_public_key IS NULL" >/dev/null

# The Gateway image runs as uid 65532 (distroless nonroot); give it its data dir
# and read access to its config + trust anchor.
chown -R 65532:65532 /gw-data
chmod 644 "$STATE/ca.pem" "$STATE/session_ca.pub" "$STATE/host_ca.pub" "$STATE/gateway.json"

log "done: CA anchors + gateway config + admin service account + customer recording key"
