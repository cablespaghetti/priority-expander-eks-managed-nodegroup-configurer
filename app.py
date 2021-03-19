import logging
import os
import sys

import re
from kubernetes import client, config
import boto3
from yaml import load, dump

try:
    from yaml import CLoader as Loader, CDumper as Dumper
except ImportError:
    from yaml import Loader, Dumper

logger = logging.getLogger()
logger.setLevel(logging.INFO)
cluster_name = os.getenv('CLUSTER_NAME')
configmap_name = os.getenv('CONFIGMAP_NAME', 'cluster-autoscaler-priority-expander-nodegroup')
if not cluster_name:
    logging.error('Please set CLUSTER_NAME environment variable')
    sys.exit(1)
cluster_autoscaler_namespace = os.getenv('CLUSTER_AUTOSCALER_NAMESPACE', 'kube-system')


def connect_to_kubernetes():
    logging.debug('Connecting to Kubernetes Cluster')
    kube_init = False
    try:
        config.load_incluster_config()
        kube_init = True
    except config.ConfigException:
        logging.warning('Failed to use incluster Kubernetes config. Trying to use local config.')

    if not kube_init:
        try:
            config.load_kube_config()
        except (TypeError, config.ConfigException):
            logging.error('Unable to connect to Kubernetes Cluster')
            sys.exit(1)


# Finds the highest priority which matches for a given node group name
def find_node_group_priority(node_group_name, priority_dict):
    priorities_list = list(priority_dict.keys())
    priorities_list.sort(reverse=True)
    for priority in priorities_list:
        for regex in priority_dict[priority]:
            if re.match(regex, node_group_name):
                logging.info(f'{node_group_name} matched {regex} for priority {priority}')
                return priority
    return None


# Gets the ConfigMap for this app and returns it as a Dictionary
def get_priority_expander_nodegroup_configuration():
    try:
        configmap = api_instance.read_namespaced_config_map(configmap_name, cluster_autoscaler_namespace)
    except client.exceptions.ApiException:
        logging.error(
            f'Problem getting {configmap_name} ConfigMap from {cluster_autoscaler_namespace}')
        return {}

    if 'priorities' in configmap.data:
        priorities_yaml = configmap.data['priorities']
        logging.debug(priorities_yaml)
        priority_dict = load(priorities_yaml, Loader=Loader)
        return priority_dict
    logging.error(f'{configmap_name} ConfigMap in {cluster_autoscaler_namespace} has no priorities')
    return {}


# Writes out the finished priority Dictionary to the ConfigMap used by Cluster Autoscaler
def write_configmap(configuration):
    priority_expander_configuration_yaml = dump(configuration, Dumper=Dumper)
    logging.debug(priority_expander_configuration_yaml)
    configmap = 'cluster-autoscaler-priority-expander'
    priority_expander_configuration_configmap = client.V1ConfigMap(
        metadata=client.V1ObjectMeta(name=configmap),
        data={'priorities': priority_expander_configuration_yaml})
    logging.info(f'Writing cluster-autoscaler-priority-expander ConfigMap to {cluster_autoscaler_namespace}')

    # Either update the ConfigMap or create it if one doesn't exist yet
    configmap_exists = True
    try:
        api_instance.read_namespaced_config_map(configmap, cluster_autoscaler_namespace)
    except client.exceptions.ApiException:
        configmap_exists = False
    if configmap_exists:
        api_instance.patch_namespaced_config_map(name=configmap, namespace=cluster_autoscaler_namespace,
                                                 body=priority_expander_configuration_configmap)
    else:
        api_instance.create_namespaced_config_map(namespace=cluster_autoscaler_namespace,
                                                  body=priority_expander_configuration_configmap)


# Works out what the lowest priority used is, and sets ".*" as 1 lower than that
def set_wildcard_priority(configuration):
    priorities_list = list(configuration.keys())
    priorities_list.sort()
    lowest_priority = priorities_list[0]
    if lowest_priority >= 1:
        configuration[lowest_priority - 1] = ['.*']
        logging.info(f'Lowest priority is {lowest_priority}, setting .* priority to {lowest_priority - 1}')
    else:
        logging.warning('Lowest priority is 1 or less. Not setting .* priority. All priorities must be > 0.')


# Read in the source ConfigMap
connect_to_kubernetes()
api_instance = client.CoreV1Api()
priorities = get_priority_expander_nodegroup_configuration()
if not priorities:
    logging.error('Failed to get priorities from ConfigMap')
    sys.exit(1)

# Get the managed node groups for our EKS cluster
eks_client = boto3.client('eks')
node_groups = eks_client.list_nodegroups(clusterName=cluster_name)['nodegroups']

# Figure out the highest priority matched by each node group (if any)
# Get the list of ASGs for that node group
# Make a Dictionary of priority: list of asg names
priority_expander_configuration = {}
for node_group in node_groups:
    node_group_priority = find_node_group_priority(node_group, priorities)
    if not node_group_priority:
        logging.warning(f'Node Group {node_group} matched no priority')
        continue

    # Get the list of node groups we've already found for this node group's priority (if any)
    priority_node_group_list = priority_expander_configuration.get(node_group_priority, [])

    # Get the ASGs for this node group
    auto_scaling_groups = \
        eks_client.describe_nodegroup(clusterName=cluster_name, nodegroupName=node_group)['nodegroup']['resources'][
            'autoScalingGroups']

    # For each ASG, add it to the list of ASGs for this priority
    for auto_scaling_group in auto_scaling_groups:
        priority_node_group_list.append(auto_scaling_group['name'])

    # Write the node group list for the priority to the Dictionary
    priority_expander_configuration[node_group_priority] = priority_node_group_list

# Work out what so set the .* priority to
set_wildcard_priority(priority_expander_configuration)

# Write the ConfigMap used by cluster autoscaler to Kubernetes
write_configmap(priority_expander_configuration)
