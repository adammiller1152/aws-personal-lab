import requests
import logging
import boto3
import json
import os

# Global variables
ACCOUNT = os.environ["ACCOUNT"]
REGION = os.environ["REGION"]
STACK = os.environ["STACK"]
LAB_VPC_CIDR = os.environ["LAB_VPC_CIDR"]
PEER_VPC_CIDR = os.environ["PEER_VPC_CIDR"]
ec2 = boto3.client("ec2", region_name=REGION)

# configure logging
primary_handler = logging.getLogger()
if primary_handler.handlers:
    for handler in primary_handler.handlers:
        primary_handler.removeHandler(handler)

logging_format = "[%(asctime)s][%(levelname)s]: %(message)s"

logging.basicConfig(
    level=logging.INFO,
    format=logging_format,
    datefmt="%Y-%m-%d %H:%M:%s"
)

logger = logging.getLogger(__name__)


# Describes the Vpcs which exist in this lab environment
def describe_lab_vpcs():
    try:
        logger.info(f"Creating a list of Vpcs inside Account: {ACCOUNT}")
        response = ec2.describe_vpcs(
            Filters=[
                {
                    "Name": "state",
                    "Values": [
                        "available"
                    ]
                },
                {
                    "Name": "tag:Name",
                    "Values": [
                        "lab*"
                    ]
                }
            ]
        )

        return response

    except Exception as err:
        logger.error(f"Received an error: {err}")


# Creates a vpc peering request based on the Vpcs discovered within describe_lab_vpcs()
def create_vpc_peering_connection(vpcs):
    try:
        logger.info("Constructing the Vpc Peering Connection request")
        for index in range(len(vpcs)):
            for tag in vpcs["Vpcs"][index]["Tags"]:
                if tag["Key"] == "Name" and tag["Value"] == "lab-vpc-2":
                    peer_vpc_id = vpcs["Vpcs"][index]["VpcId"]
                elif tag["Key"] == "Name" and tag["Value"] == "lab-vpc-1":
                    vpc_id = vpcs["Vpcs"][index]["VpcId"]
                else:
                    pass

        logger.info("Attempting to initiate the Vpc Peering Connection request")
        response = ec2.create_vpc_peering_connection(
            PeerVpcId=peer_vpc_id,
            VpcId=vpc_id
        )

        peering_connection_id = response["VpcPeeringConnection"]["VpcPeeringConnectionId"]
        logger.info(f"Successfully initiated Vpc Peering Connection Request, Connection Id: {peering_connection_id}")

        return {
            "StatusCode": 200,
            "Peering_Connection_Id": peering_connection_id,
            "Peer_Vpc_Id": peer_vpc_id,
            "Lab_Vpc_Id": vpc_id,
            "Message": "OK"
        }

    except Exception as err:
        return {
            "StatusCode": 400,
            "Message": err
        }

# Accepts the Vpc peering request created by create_vpc_peering_connection(vpcs)
def accept_vpc_peering_connection(vpc_peering_connection_id):
    try:
        logger.info("Attempting to accept the Vpc Peering Request")
        response = ec2.accept_vpc_peering_connection(
            VpcPeeringConnectionId=vpc_peering_connection_id
        )

        logger.info("Successfully accepted the Vpc Peering Request")
        return {
            "StatusCode": 200,
            "Message": "OK"
        }

    except Exception as err:
        return {
            "StatusCode": 400,
            "Message": err
        }

# Update the Routes between the two VPCs
def update_routes(vpc_peering_connection, peer_vpc_id, lab_vpc_id, event_type):
    try:
        vpcs = [peer_vpc_id, lab_vpc_id]
        logger.info(f"Attempting to find the route tables associated with the following Vpcs: {vpcs}")
        lab_route_tables = []
        peer_route_tables = []

        for vpc in vpcs:
            route_tables = ec2.describe_route_tables(
                Filters=[
                    {
                        "Name": "vpc-id",
                        "Values": [
                            vpc
                        ]
                    }
                ]
            )

            for table in route_tables["RouteTables"]:
                if table["VpcId"] == peer_vpc_id:
                    peer_route_tables.append(table["RouteTableId"])
                elif table["VpcId"] == lab_vpc_id:
                    lab_route_tables.append(table["RouteTableId"])
                else:
                    pass

        logger.info(f"Found the following route tables for {lab_vpc_id}: {lab_route_tables}")
        logger.info(f"Found the following route tables for {peer_vpc_id}: {peer_route_tables}")

        logger.info(f"Updating Routes for Vpc: {lab_vpc_id}")
        for route_table_id in lab_route_tables:
            if event_type == "Delete":
                response = ec2.delete_route(
                    DestinationCidrBlock=PEER_VPC_CIDR,
                    RouteTableId=route_table_id
                )
            else:
                response = ec2.create_route(
                    DestinationCidrBlock=PEER_VPC_CIDR,
                    VpcPeeringConnectionId=vpc_peering_connection,
                    RouteTableId=route_table_id
                )

        logger.info(f"Updating routes for Vpc: {peer_vpc_id}")
        for route_table_id in peer_route_tables:
            if event_type == "Delete":
                response = ec2.delete_route(
                    DestinationCidrBlock=LAB_VPC_CIDR,
                    RouteTableId=route_table_id
                )
            else:
                response = ec2.create_route(
                    DestinationCidrBlock=LAB_VPC_CIDR,
                    VpcPeeringConnectionId=vpc_peering_connection,
                    RouteTableId=route_table_id
                )

        logger.info("Successfully updated routes")

        return {
            "StatusCode": 200,
            "Message": "OK"
        }

    except Exception as err:
        return {
            "StatusCode": 400,
            "Message": err
        }

# Determines the Vpc peering connection id in order to pass it to delete_peering_connection(vpc_peering_connection_id)
def get_vpc_peering_connection_id(vpcs):
    try:
        logger.info("Attempting to find the Vpc Peering Connection Id")
        for index in range(len(vpcs)):
            for tag in vpcs["Vpcs"][index]["Tags"]:
                if tag["Key"] == "Name" and tag["Value"] == "lab-vpc-2":
                    peer_vpc_id = vpcs["Vpcs"][index]["VpcId"]
                elif tag["Key"] == "Name" and tag["Value"] == "lab-vpc-1":
                    vpc_id = vpcs["Vpcs"][index]["VpcId"]
                else:
                    pass

        response = ec2.describe_vpc_peering_connections(
            Filters=[
                {
                    "Name": "status-code",
                    "Values": [
                        "active",
                        "pending-acceptance",
                        "provisioning"
                    ]
                },
                {
                    "Name": "accepter-vpc-info.vpc-id",
                    "Values": [
                        peer_vpc_id
                    ]
                },
                {
                    "Name": "requester-vpc-info.vpc-id",
                    "Values": [
                        vpc_id
                    ]
                }
            ]
        )

        peering_connection_id = response["VpcPeeringConnections"][0]["VpcPeeringConnectionId"]
        logger.info(f"Successfully found the Vpc Peering Connection Id, Connection Id: {peering_connection_id}")

        return {
            "StatusCode": 200,
            "Peering_Connection_Id": peering_connection_id,
            "Peer_Vpc_Id": peer_vpc_id,
            "Lab_Vpc_Id": vpc_id,
            "Message": "OK"
        }

    except Exception as err:
        return {
            "StatusCode": 400,
            "Message": err
        }

# Deletes the Vpc peering connection returned from get_vpc_peering_connection_id(vpcs)
def delete_peering_connection(vpc_peering_connection_id):
    try:
        logger.info(f"Attempting to delete Vpc Peering Connection, Connection Id: {vpc_peering_connection_id}")
        response = ec2.delete_vpc_peering_connection(
            VpcPeeringConnectionId=vpc_peering_connection_id
        )

        logger.info("Successfully deleted Vpc Peering Connection")

        return {
            "StatusCode": 200,
            "Message": "OK"
        }

    except Exception as err:
        return {
            "StatusCode": 400,
            "Message": err
        }


# The Lambda Handler
def lambda_handler(event, context):
    request_type = event.get("RequestType", None)

    logger.info(f"Received a {request_type} event from CloudFormation Stack: {STACK}")
    logger.info(event)

    response_url = event.get("ResponseURL", None)

    response_data = {}
    response_data["StackId"] = event.get("StackId", None)
    response_data["RequestId"] = event.get("RequestId", None)
    response_data["RequestType"] = event.get("RequestType", None)
    response_data["LogicalResourceId"] = event.get("LogicalResourceId", None)
    response_data["PhysicalResourceId"] = event.get("PhysicalResourceId", f"{context.function_name}-{context.function_version}")
    response_data["Data"] = {}
    response_data["Data"]["Reason"] = "Review CloudWatch Logs for additional details"

    if event.get("RequestType") == "Delete":

        vpcs = describe_lab_vpcs()
        get_vpc_peering_connection_id_response = get_vpc_peering_connection_id(vpcs)
        update_route_tables_response = update_routes(get_vpc_peering_connection_id_response["Peering_Connection_Id"], get_vpc_peering_connection_id_response["Peer_Vpc_Id"], get_vpc_peering_connection_id_response["Lab_Vpc_Id"], event.get("RequestType"))
        delete_peering_connection_response = delete_peering_connection(get_vpc_peering_connection_id_response["Peering_Connection_Id"])

        if delete_peering_connection_response["StatusCode"] == 400:
            response_data["Status"] = "Failed"
            response_data["Reason"] = delete_peering_connection_response["Message"]
        elif get_vpc_peering_connection_id_response["StatusCode"] == 400:
            response_data["Status"] = "Failed"
            response_data["Reason"] = get_vpc_peering_connection_id_response["Message"]
        else:
            response_data["Status"] = "SUCCESS"
            response_data["Reason"] = "Received a Delete Request from CloudFormation"

    else:

        vpcs = describe_lab_vpcs()
        create_vpc_peering_connection_response = create_vpc_peering_connection(vpcs)
        accept_vpc_peering_connection_response = accept_vpc_peering_connection(create_vpc_peering_connection_response["Peering_Connection_Id"])
        update_route_tables_response = update_routes(create_vpc_peering_connection_response["Peering_Connection_Id"], create_vpc_peering_connection_response["Peer_Vpc_Id"], create_vpc_peering_connection_response["Lab_Vpc_Id"], event.get("RequestType"))

        if create_vpc_peering_connection_response["StatusCode"] == 400:
            response_data["Status"] = "Failed"
            response_data["Reason"] = create_vpc_peering_connection_response["Message"]
        elif accept_vpc_peering_connection_response["StatusCode"] == 400:
            response_data["Status"] = "Failed"
            response_data["Reason"] = accept_vpc_peering_connection_response["Message"]

        else:
            response_data["Status"] = "SUCCESS"
            response_data["Data"]["VpcPeeringConnectionId"] = create_vpc_peering_connection_response["Peering_Connection_Id"]
            response_data["Data"]["Reason"] = "OK"

    json_response = json.dumps(response_data)

    try:
        logger.info(f"Attempting to send response to CloudFormation Stack: {STACK}")
        response = requests.put(
            response_url,
            data = json_response
        )
        logger.info("Message sent successfully")

    except Exception as err:
        logger.error(f"Message failed to send: {err}")
        raise

    return response_data