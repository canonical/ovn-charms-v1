# Overview

This charm provides the Open Virtual Network (OVN) local controller, Open
vSwitch Database and Switch.

On successful deployment the unit will be enlisted as a `Chassis` in the OVN
network.

Open vSwitch bridges for integration, external Layer2 and Layer3 connectivity
is managed by the charm.

> **Note**: The OVN charms are considered preview charms.

# Usage

OVN makes use of Public Key Infrastructure (PKI) to authenticate and authorize
control plane communication.  The charm requires a Certificate Authority to be
present in the model as represented by the `certificates` relation.

There is a [OVN overlay bundle](https://github.com/openstack-charmers/openstack-bundles/blob/master/development/overlays/openstack-base-ovn.yaml)
for use in conjunction with the [OpenStack Base bundle](https://github.com/openstack-charmers/openstack-bundles/blob/master/development/openstack-base-bionic-train/bundle.yaml)
which give an example of how you can automate certificate lifecycle management
with the help from [Vault](https://jaas.ai/vault/).

## Network Spaces support

This charm supports the use of Juju Network Spaces.

By binding the `ovsdb` endpoint you can influence which interface will be used
for communication with the OVN Southbound DB as well as overlay traffic.

    juju deploy ovn-dedicated-chassis --bind "ovsdb=data-space"

## Port Configuration

Chassis port configuration is composed of a mapping between physical network
names to bridge names (`ovn-bridge-mappings`) and individual interface to
bridge names (`interface-bridge-mappings`).  There must be a match in both
configuration options before the charm will configure bridge and interfaces on
a unit.

The physical network name can be referenced when the administrator programs the
OVN logical flows, either by talking directly to the Northbound database, or by
interfaceing with a Cloud Management System (CMS).

Networks for use with external Layer3 connectivity should have mappings on
chassis located in the vicinity of the datacenter border gateways.  Having two
or more chassis with mappings for a Layer3 network will have OVN automatically
configure highly available routers with liveness detection provided by the
Bidirectional Forwarding Detection (BFD) protocol.

Chassis without direct external mapping to a external Layer3 network will
forward traffic through a tunnel to one of the chassis acting as a gateway for
that network.

> **Note**: It is not necessary nor recommended to add mapping for external
  Layer3 networks to all chassis.  Doing so will create a scaling problem at
  the physical network layer that needs to be resolved with globally shared
  Layer2 (does not scale) or tunneling at the top-of-rack switch layer (adds
  complexity) and is generally not a recommended configuration.

Networks for use with external Layer2 connectivity should have mappings present
on all chassis with potential to host the consuming payload.

# Bugs

Please report bugs on [Launchpad](https://bugs.launchpad.net/charm-ovn-chassis/+filebug).

For general questions please refer to the OpenStack [Charm Guide](https://docs.openstack.org/charm-guide/latest/).
