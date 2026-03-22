from __future__ import annotations

from scripts import aws_dev_recovery_i17


def test_build_replacement_plan_uses_source_baseline_and_overrides() -> None:
    source_instance = {
        "InstanceId": "i-source",
        "ImageId": "ami-base",
        "InstanceType": "t3.small",
        "SubnetId": "subnet-123",
        "SecurityGroups": [{"GroupId": "sg-a"}, {"GroupId": "sg-b"}],
        "IamInstanceProfile": {
            "Arn": "arn:aws:iam::123456789012:instance-profile/auraxis-dev-role"
        },
        "KeyName": "auraxis-dev",
        "Tags": [{"Key": "Name", "Value": "auraxis_dev"}],
    }
    elastic_ip = {"AllocationId": "eipalloc-123", "PublicIp": "203.0.113.10"}

    plan = aws_dev_recovery_i17.build_replacement_plan(
        source_instance=source_instance,
        elastic_ip=elastic_ip,
        replacement_name="auraxis_dev_replacement",
        git_ref="origin/master",
        domain="dev.api.auraxis.com.br",
        ssm_path="/auraxis/dev",
    )

    assert plan.source_instance_id == "i-source"
    assert plan.source_name == "auraxis_dev"
    assert plan.replacement_name == "auraxis_dev_replacement"
    assert plan.image_id == "ami-base"
    assert plan.instance_type == "t3.small"
    assert plan.subnet_id == "subnet-123"
    assert plan.security_group_ids == ("sg-a", "sg-b")
    assert plan.iam_instance_profile_name == "auraxis-dev-role"
    assert plan.key_name == "auraxis-dev"
    assert plan.elastic_ip_allocation_id == "eipalloc-123"


def test_build_bootstrap_script_materializes_env_from_ssm() -> None:
    plan = aws_dev_recovery_i17.InstanceLaunchPlan(
        source_instance_id="i-source",
        source_name="auraxis_dev",
        replacement_name="auraxis_dev_replacement",
        image_id="ami-base",
        instance_type="t3.small",
        subnet_id="subnet-123",
        security_group_ids=("sg-a",),
        iam_instance_profile_name="auraxis-dev-role",
        key_name="auraxis-dev",
        elastic_ip_allocation_id="eipalloc-123",
        elastic_ip_public_ip="203.0.113.10",
        domain="dev.api.auraxis.com.br",
        ssm_path="/auraxis/dev",
        git_ref="origin/master",
    )

    script = aws_dev_recovery_i17._build_bootstrap_script(plan, aws_region="us-east-1")

    assert "scripts/sync_cloud_secrets.py" in script
    assert "--base-env .env.prod.example" in script
    assert '--ssm-path "/auraxis/dev"' in script
    assert '--set "DOMAIN=dev.api.auraxis.com.br"' in script
    assert 'git -C /opt/auraxis reset --hard "origin/master"' in script
