# Copyright 2018-2020 Red Hat, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
import logging
import re

from ovirtsdk4.types import Bonding, HostNic, Option

from . import constants as const


def filter_vlan_tag(tlvs):
    filtered_tlvs = []
    for tlv in tlvs:
        if (tlv.type == const.PORT_VLAN_TYPE and tlv.oui == const.PORT_VLAN_OUI
                and tlv.subtype == const.PORT_VLAN_SUBTYPE):
            filtered_tlvs.extend(tlv.properties)
    return filtered_tlvs


def create_label_candidates(tlv_properties):
    label_candidates = []
    for property in tlv_properties:
        if property.name == const.PROPERTY_VLAN_NAME:
            label_candidates.append(const.LABEL_PREFIX + property.value)
    return label_candidates


def get_or_query(param, values):
    return ' OR '.join(['{}={}'.format(param, val) for val in values])


def filter_out_vlan_interfaces(nic_list):
    return [nic for nic in nic_list if nic.vlan is None]


def filter_out_bond_slaves(nic_list):
    slave_list = []
    for nic in nic_list:
        if nic.bonding is not None:
            slave_list.extend([slave.id for slave in nic.bonding.slaves])
    return [nic for nic in nic_list if nic.id not in slave_list]


def filter_link_aggregation(tlvs):
    for tlv in tlvs:
        if (tlv.type == const.LINK_AGGREGATION_TYPE
                and tlv.oui == const.LINK_AGGREGATION_OUI
                and tlv.subtype == const.LINK_AGGREGATION_SUBTYPE):
            return tlv.properties
    return []


def _is_currently_aggregated(properties):
    prop_val = [
        prop.value for prop in properties
        if (prop.name == const.PROPERTY_LINK_AGGREGATION_AGGREGATED
            and prop.value == const.PROPERTY_TRUE)
    ]
    return len(prop_val) > 0


def find_next_bond_num(nic_names):
    bond_names = [
        nic_name for nic_name in nic_names if re.search(r'bond.*', nic_name)
    ]
    bond_names.sort()
    return int(bond_names[0].strip('bond')) + 1 if len(bond_names) > 0 else 0


def update_bond_dict(bond_dict, tlvs, nic):
    link_aggregation_properties = filter_link_aggregation(tlvs)
    aggregation_port_id = next(
        (prop.value for prop in link_aggregation_properties if
         prop.name == const.PROPERTY_LINK_AGGREGATION_ID), None)
    if aggregation_port_id is None:
        return
    logging.info('Found active port aggregation group %s for nic %s',
                 aggregation_port_id, nic.name)
    slave_list = bond_dict.get(aggregation_port_id)
    if slave_list is None:
        bond_dict.update({aggregation_port_id: [nic]})
    else:
        slave_list.append(nic)


def create_bond_definition(nic_list, next_bond_num):
    slaves_list = [HostNic(id=nic.id) for nic in nic_list]
    if len(slaves_list) > 1:
        bonding = Bonding(
            options=[
                Option(
                    name=const.BOND_MODE_OPTION_NAME,
                    value=const.BOND_MODE_OPTION_VALUE)
            ],
            slaves=slaves_list)
        bond_name = const.BOND_PREFIX + str(next_bond_num)
        logging.info('Creating bond %s with slaves: %s', bond_name,
                     ', '.join([nic.name for nic in nic_list]))
        return HostNic(name=bond_name, bonding=bonding)
    else:
        return None


def create_network_list(nic_list, network_dict):
    network_list = []
    for nic in nic_list:
        networks = network_dict.get(nic, [])
        network_list.extend(networks)
    return network_list


def create_attachment_definition(nic_list, next_bond_num, attachment_dict):
    attachments_list = []
    bond_name = const.BOND_PREFIX + str(next_bond_num)
    for nic in nic_list:
        attachments = attachment_dict.get(nic, [])
        for attachment in attachments:
            attachment.host_nic = HostNic(name=bond_name)
            attachments_list.append(attachment)
    return attachments_list


def filter_bond_slaves_by_attachments(nic_list, network_dict):
    checked_nic_list = []
    bond_has_non_vlan_network_already = False
    for nic in nic_list:
        networks = network_dict.get(nic)
        if networks and not _contains_managment_network(networks):
            contains_non_vlan_network = _contains_non_vlan_network(networks)
            if (contains_non_vlan_network
                    and not bond_has_non_vlan_network_already):
                bond_has_non_vlan_network_already = True
                checked_nic_list.append(nic)
            elif not contains_non_vlan_network:
                checked_nic_list.append(nic)
    return checked_nic_list


def _contains_managment_network(networks):
    return len([
        network for network in networks
        if network.name == const.OVIRT_MANAGMENT_NETWORK
    ]) > 0


def _contains_non_vlan_network(networks):
    return len([network for network in networks if network.vlan is None]) > 0
