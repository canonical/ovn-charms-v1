# Copyright 2026 Canonical Ltd
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""The neutron-plugin-remote metadata protocol for remotely managed chassis.

Nova advertises the credentials it already uses for its local metadata proxy.
Each DPU consumes an address and secret from the same compute unit. Different
compute units can therefore retain their local, per-unit secrets.
"""

from charms.reactive import Endpoint, toggle_flag, when, when_not


METADATA_KEY = 'metadata-shared-secret'


class NeutronPluginRemoteProvides(Endpoint):
    """Consume credentials from Nova over the remote plugin relation."""

    @when('endpoint.{endpoint_name}.joined')
    @when_not('is-update-status-hook')
    def manage_flags(self):
        """Enable the shared OVN handlers once host and secret are available.

        The reactive handler also runs during upgrade-charm, when Endpoint may
        skip automatic flag management. Withdraw credentials sent by older DPU
        revisions even if Nova has not advertised a usable endpoint yet.
        """
        self.publish_shared_secret()
        ready = bool(self.metadata_host)
        toggle_flag(self.expand_name('{endpoint_name}.connected'), ready)

    @property
    def metadata_endpoint(self):
        """Select one compute unit's complete (address, secret) pair.

        Endpoint orders joined units by relation ID and unit name and excludes
        departing units. Skip incomplete advertisements rather than combining
        one unit's address with another unit's credentials. Relation data is a
        snapshot for the hook, so both template accessors select the same unit.
        """
        for unit in self.all_joined_units:
            data = unit.received_raw
            address = data.get('private-address')
            secret = data.get(METADATA_KEY)
            if address and secret and secret.strip():
                return address, secret
        return None, None

    @property
    def metadata_host(self):
        """Address of the compute API whose credentials we consume."""
        return self.metadata_endpoint[0]

    def get_or_create_shared_secret(self):
        """Read-only compatibility accessor for the shared OVN layer.

        The layer calls this legacy method name from its relation adapter.
        Remote chassis must never create or change Nova's shared secret.
        """
        return self.metadata_endpoint[1]

    def publish_shared_secret(self):
        """Withdraw obsolete DPU credentials; never publish a new secret.

        The shared OVN layer calls this method on activation. Setting a value
        to None removes it from Juju relation data, including on upgrades from
        the earlier protocol where DPUs generated independent credentials.
        """
        for relation in self.relations:
            if METADATA_KEY in relation.to_publish_raw:
                relation.to_publish_raw[METADATA_KEY] = None
