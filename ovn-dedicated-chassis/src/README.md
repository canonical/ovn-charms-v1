# Overview

The ovn-dedicated-chassis charm provides the Open Virtual Network (OVN) local
controller, Open vSwitch Database and Switch. It is used in conjunction with
the [ovn-central][ovn-central-charm] charm.

Open vSwitch bridges for integration, external Layer2 and Layer3 connectivity
is managed by the charm.

On successful deployment the unit will be enlisted as a Chassis in the OVN
network.

The ovn-dedicated-chassis charm is a principle charm that sets up a software
gateway on a dedicated host. Alternatively, the subordinate
[ovn-chassis][ovn-chassis-charm] charm can be used.

> **Note**: The OVN charms are supported starting with OpenStack Train.

# Usage

The [OpenStack Base bundle][openstack-base-bundle] gives an example of how you
can deploy OpenStack and OVN with [Vault][vault-charm] to automate certificate
lifecycle management.

OVN makes use of Public Key Infrastructure (PKI) to authenticate and authorize
control plane communication. The charm therefore requires a Certificate
Authority to be present in the model as represented by the `certificates`
relation.

Refer to [Open Virtual Network (OVN)][cdg-ovn] in the [OpenStack Charms
Deployment Guide][cdg] for details, including deployment steps.

This charm provides the Open Virtual Network (OVN) local controller, Open
vSwitch Database and Switch.

On successful deployment the unit will be enlisted as a `Chassis` in the OVN
network.

Open vSwitch bridges for integration, external Layer2 and Layer3 connectivity
is managed by the charm.

## Network spaces

This charm supports the use of Juju network spaces.

By binding the `ovsdb` endpoint you can influence which interface will be used
for communication with the OVN Southbound DB as well as overlay traffic.

    juju deploy ovn-dedicated-chassis --bind "ovsdb=internal-space"

By binding the `data` extra-binding you can influence which interface will be
used for overlay traffic.

    juju deploy ovn-dedicated-chassis --bind "data=overlay-space"

## Port configuration

Chassis port configuration is composed of a mapping between physical network
names to bridge names (`ovn-bridge-mappings`) and individual interface to
bridge names (`bridge-interface-mappings`). There must be a match in both
configuration options before the charm will configure bridge and interfaces on
a unit.

The physical network name can be referenced when the administrator programs the
OVN logical flows, either by talking directly to the Northbound database, or by
interfacing with a Cloud Management System (CMS).

Networks for use with external Layer3 connectivity should have mappings on
chassis located in the vicinity of the datacenter border gateways. Having two
or more chassis with mappings for a Layer3 network will have OVN automatically
configure highly available routers with liveness detection provided by the
Bidirectional Forwarding Detection (BFD) protocol.

Chassis without direct external mapping to a external Layer3 network will
forward traffic through a tunnel to one of the chassis acting as a gateway for
that network.

> **Note**: It is not necessary, nor recommended, to add mapping for external
  Layer3 networks to all chassis. Doing so will create a scaling problem at the
  physical network layer that needs to be resolved with globally shared Layer2
  (does not scale) or tunneling at the top-of-rack switch layer (adds
  complexity) and is generally not a recommended configuration.

Networks for use with external Layer2 connectivity should have mappings present
on all chassis with potential to host the consuming payload.

## Metadata for remote-managed ports

When this charm runs on a SmartNIC DPU, instances using
[remote-managed ports][ovn-smartnic-dpu] need a Neutron OVN metadata agent on
the DPU. The `nova-compute` relation enables this agent using the credentials
already configured for a related compute host's local `ovn-chassis` metadata
proxy. Nova transmits those credentials to the DPU; the DPU does not generate a
secret or change the credentials used by local instances.

This requires a nova-compute charm implementing the `neutron-plugin-remote`
endpoint with the `neutron-plugin-remote` interface and global scope. Its existing
`neutron-plugin` endpoint retains container scope for colocated subordinates.
The new endpoint is declared in nova-compute's `metadata.yaml` as follows:

```yaml
requires:
  neutron-plugin-remote:
    interface: neutron-plugin-remote
    scope: global
```

Each Nova unit must publish the following raw unit relation data after
configuring its local metadata API:

* `private-address`: the compute metadata API address, reachable on port 8775.
* `metadata-shared-secret`: the secret already used by that unit's local
  metadata proxy.

Nova must refresh this advertisement when local credentials change and withdraw
the secret when local signed metadata is unavailable. Incoming DPU credentials
must not configure Nova's metadata API. Versions of Nova that only consume a
DPU-generated secret need the companion credential-forwarding update.

With a compatible nova-compute charm deployed, add the relation:

    juju integrate ovn-dedicated-chassis:nova-compute nova-compute:neutron-plugin-remote

The DPU must be able to reach the compute hosts' relation addresses on TCP port
8775. Relate the dedicated chassis application to the compute application for
its Nova cell. A compute API can serve metadata for instances on other hosts in
that cell, including after migration.

Keep the existing `nova-compute` / `ovn-chassis` relation when adding dedicated
chassis. The DPU automatically adopts existing credentials, so no secret
configuration or reconciliation action is needed. This also works when the
local provider is established after the DPU relation: the DPU waits for a
complete advertisement before enabling metadata.

Compute units may have different local secrets. Each DPU selects the first
complete advertisement, ordered by relation ID and unit name, and always uses
the address and secret from that same unit. It re-renders the agent
configuration on credential changes. If the selected unit leaves the relation
or withdraws its credentials, the DPU selects another complete pair. It waits
if none remain; it never combines credentials from different compute units.

When upgrading from an earlier DPU revision that generated its own secret,
upgrade both charms to the credential-forwarding protocol. The DPU clears its
obsolete outgoing secret automatically, and Nova retains the local provider's
credentials throughout. No local metadata relation needs to be removed.

The existing `ovsdb` and `certificates` relations are also required. Once the
relation is ready, the charm installs and manages `neutron-ovn-metadata-agent`
and renders `/etc/neutron/neutron_ovn_metadata_agent.ini` on each DPU. This
allows instances to obtain metadata without requiring config-drive. It does not
change Nova's other restrictions on migrating remote-managed PCI devices.

## Deferred service events

Operational or maintenance procedures applied to a cloud often lead to the
restarting of various OpenStack services and/or the calling of certain charm
hooks. Although normal, such events can be undesirable due to the service
interruptions they can cause.

The deferred service events feature provides the operator the choice of
preventing these service restarts and hook calls from occurring, which can then
be resolved at a more opportune time.

See the [Deferred service events][cdg-deferred-service-events] page in the
[OpenStack Charms Deployment Guide][cdg] for an in-depth treatment of this
feature.

# Bugs

Please report bugs on [Launchpad][lp-ovn-dedicated-chassis].

For general questions please refer to the [OpenStack Charm Guide][cg].

<!-- LINKS -->

[cg]: https://docs.openstack.org/charm-guide/latest/
[cdg]: https://docs.openstack.org/project-deploy-guide/charm-deployment-guide/latest/
[cdg-ovn]: https://docs.openstack.org/project-deploy-guide/charm-deployment-guide/latest/app-ovn.html
[vault-charm]: https://jaas.ai/vault/
[lp-ovn-dedicated-chassis]: https://bugs.launchpad.net/charm-ovn-dedicated-chassis/+filebug
[ovn-central-charm]: https://jaas.ai/ovn-central
[ovn-chassis-charm]: https://jaas.ai/ovn-chassis
[openstack-base-bundle]: https://github.com/openstack-charmers/openstack-bundles/blob/master/development/openstack-base-bionic-ussuri-ovn/bundle.yaml
[cdg-deferred-service-events]: https://docs.openstack.org/project-deploy-guide/charm-deployment-guide/latest/deferred-events.html
[ovn-smartnic-dpu]: https://docs.openstack.org/neutron/latest/admin/ovn/smartnic_dpu.html
