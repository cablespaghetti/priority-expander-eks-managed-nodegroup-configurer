# Priority Expander EKS Managed Node group configurer

Generates the `cluster-autoscaler-priority-expander` ConfigMap expected by the Kubernetes Cluster Autoscaler's [priority expander](https://github.com/kubernetes/autoscaler/blob/master/cluster-autoscaler/expander/priority/readme.md) containing the Auto Scaling Group names rather than the names of the node groups.

This runs as a CronJob every 5 minutes and can be deployed with the Helm Chart in this repository. It must be deployed in the same namespace as cluster autoscaler. Currently a number of things including the [input configmap](./charts/priority-expander-configurer/templates/configmap.yaml) are hardcoded in the chart.

The chart creates all the RBAC you need but it will need to have some AWS permissions to do the following:

```
        "eks:DescribeNodegroup",
        "eks:ListNodegroups"
```

These can be assigned via the EC2 instance profile, or assigned to the Pod via kiam, kube2iam or the EKS IAM Roles for service accounts feature.

Built as a temporary solution to solve: https://github.com/kubernetes/autoscaler/issues/3871

Hopefully this issue will be fixed by AWS so this tool will no longer be required: https://github.com/aws/containers-roadmap/issues/1304