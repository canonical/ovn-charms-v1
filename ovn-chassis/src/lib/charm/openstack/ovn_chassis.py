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

import os

from charmhelpers.core.host import rsync, write_file
from charmhelpers.contrib.charmsupport import nrpe
import charmhelpers.fetch as ch_fetch

import charms_openstack.charm as charm

import charms.ovn_charm

NAGIOS_PLUGINS = '/usr/local/lib/nagios/plugins'
SCRIPTS_DIR = '/usr/local/bin'
CERTCHECK_CRONFILE = '/etc/cron.d/ovn-chassis-cert-checks'
CRONJOB_CMD = "{schedule} root {command} 2>&1 | logger -p local0.notice\n"


charm.use_defaults('charm.default-select-release')


class OVNChassisCharm(charms.ovn_charm.DeferredEventMixin,
                      charms.ovn_charm.BaseOVNChassisCharm):
    # OpenvSwitch and OVN is distributed as part of the Ubuntu Cloud Archive
    # Pockets get their name from OpenStack releases.
    #
    # This defines the earliest version this charm can support, actually
    # installed version is selected by the principle charm.
    release = 'ussuri'
    name = 'ovn-chassis'

    # packages needed by nrpe checks
    nrpe_packages = ['python3-cryptography']

    # Setting an empty source_config_key activates special handling of release
    # selection suitable for subordinate charms
    source_config_key = ''

    @property
    def packages(self):
        return super().packages + self.nrpe_packages

    def render_nrpe(self):
        hostname = nrpe.get_nagios_hostname()
        self.add_nrpe_certs_check(nrpe.NRPE(hostname=hostname))
        super().render_nrpe()

    def add_nrpe_certs_check(self, charm_nrpe):
        script = 'nrpe_check_ovn_certs.py'
        src = os.path.join(os.getenv('CHARM_DIR'), 'files', 'nagios', script)
        dst = os.path.join(NAGIOS_PLUGINS, script)
        rsync(src, dst)
        charm_nrpe.add_check(
            shortname='check_ovn_certs',
            description='Check that ovn certs are valid.',
            check_cmd=script
        )
        # Need to install this as a system package since it is needed by the
        # cron script that runs outside of the charm.
        ch_fetch.apt_install(['python3-cryptography'])
        script = 'check_ovn_certs.py'
        src = os.path.join(os.getenv('CHARM_DIR'), 'files', 'scripts', script)
        dst = os.path.join(SCRIPTS_DIR, script)
        rsync(src, dst)
        cronjob = CRONJOB_CMD.format(
            schedule='*/15 * * * *',
            command=dst)
        write_file(CERTCHECK_CRONFILE, cronjob)
