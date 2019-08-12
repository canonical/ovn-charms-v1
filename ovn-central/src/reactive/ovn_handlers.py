# Copyright 2019 Canonical Ltd
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

import charmhelpers.contrib.openstack.cert_utils as cert_utils
import charms.reactive as reactive
import charms_openstack.bus
import charms_openstack.charm as charm


charms_openstack.bus.discover()

# Use the charms.openstack defaults for common states and hooks
charm.use_defaults(
    'charm.installed',
    'config.changed',
    'update-status',
    'upgrade-charm')


@reactive.when('certificates.available')
def request_certificates(tls):
    with charm.provide_charm_instance() as instance:
        for cn, req in cert_utils.get_certificate_request(
                json_encode=False).get('cert_requests', {}).items():
            tls.add_request_server_cert(cn, req['sans'])
        tls.request_server_certs()
        # make charms.openstack required relation check happy
        reactive.set_flag('certificates.connected')
        instance.assess_status()


@reactive.when_any(
    'certificates.ca.changed',
    'certificates.server.certs.changed')
def render(*args):
    with charm.provide_charm_instance() as instance:
        instance.render_with_interfaces(args)
    reactive.clear_flag('certificates.ca.changed')
    reactive.clear_flag('certificates.server.certs.changed')
    instance.assess_status()
