import json, boto3, logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

import requests
import json
 
SUCCESS = "SUCCESS"
FAILED = "FAILED"
dynamodb = boto3.resource('dynamodb')

def lambda_handler(event, context):
    logger.info("event: {}".format(event))
    try:
        tableName = event['ResourceProperties']['TableName']
        table = dynamodb.Table(tableName)
        quickSightAccount = event['ResourceProperties']['QuickSightAccount']
        additionalAccounts = event['ResourceProperties']['AdditionalAccounts'] if len(event['ResourceProperties']['AdditionalAccounts']) != 0 else [] 
        logger.info("tableName: {}, event['RequestType']: {}".format(tableName,event['RequestType']))
        logger.info("quickSightAccount: {}, additionalAccounts: {}".format(quickSightAccount,additionalAccounts))
        if event['RequestType'] != 'Delete':                        
            response = table.put_item(
              Item={
                    'accountid': quickSightAccount,
                    'first_import': "true",
                    'bucket': "quicksight-data-" + quickSightAccount,
                    'additional_accountsids': additionalAccounts
                }
            )   
            logger.info("put_item: {}".format(response))                     

        sendResponseCfn(event, context, SUCCESS)
    except Exception as e:
        logger.info("Exception: {}".format(e))
        sendResponseCfn(event, context, FAILED)

#def sendResponseCfn(event, context, responseStatus):
#    responseData = {}
#    responseData['Data'] = {}
#    cfnresponse.send(event, context, responseStatus, responseData, "CustomResourcePhysicalID")
    
def sendResponseCfn(event, context, responseStatus, physicalResourceId=None, noEcho=False):
    responseData = {}
    responseData['Data'] = {}  
    responseUrl = event['ResponseURL']
 
    print(responseUrl)
 
    responseBody = {}
    responseBody['Status'] = responseStatus
    responseBody['Reason'] = 'See the details in CloudWatch Log Stream: ' + context.log_stream_name
    responseBody['PhysicalResourceId'] = physicalResourceId or context.log_stream_name
    responseBody['StackId'] = event['StackId']
    responseBody['RequestId'] = event['RequestId']
    responseBody['LogicalResourceId'] = event['LogicalResourceId']
    responseBody['NoEcho'] = noEcho
    responseBody['Data'] = responseData
 
    json_responseBody = json.dumps(responseBody)
 
    print("Response body:\n" + json_responseBody)
 
    headers = {
        'content-type' : '',
        'content-length' : str(len(json_responseBody))
    }
 
    try:
        response = requests.put(responseUrl,
                                data=json_responseBody,
                                headers=headers)
        print("Status code: " + response.reason)
    except Exception as e:
        print("send(..) failed executing requests.put(..): " + str(e))    