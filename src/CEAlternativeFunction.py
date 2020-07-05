import boto3
from datetime import datetime
import csv, logging, json, os
from dateutil.relativedelta import relativedelta

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table(os.environ['TABLE_NAME'])
ce_client = boto3.client('ce', 'us-east-1')
s3_client = boto3.client('s3')
s3_resource = boto3.resource('s3')
param_objects = {
    'group_by_instance_type': {'labels':['InstanceType','Service'], 'groupby_1_type':'DIMENSION','groupby_1_key':'INSTANCE_TYPE','groupby_2_type':'DIMENSION','groupby_2_key':'SERVICE'},    
    'group_by_usage_type': {'labels':['UsageType','Service'], 'groupby_1_type':'DIMENSION','groupby_1_key':'USAGE_TYPE','groupby_2_type':'DIMENSION','groupby_2_key':'SERVICE'},
    'group_by_tag_environment': {'labels':['Tag-Environment','Service'], 'groupby_1_type':'TAG','groupby_1_key':'environment','groupby_2_type':'DIMENSION','groupby_2_key':'SERVICE'}
    }

def lambda_handler(event, context):
    
    response = table.scan()
    logger.info("items of dynamodb {}".format(response['Items']))
    for accountItem in response['Items']:
        today = datetime.today()
        firstOfThisMonth = datetime(today.year, today.month, 1)
        secondOfThisMonth = datetime(today.year, today.month, 2)
        last_month = today + relativedelta(months=-1)
        firstOfLastMonth = datetime(last_month.year, last_month.month, 1) 
        
        if accountItem['first_import'].lower() == 'true':
            bucket = s3_resource.Bucket(accountItem['bucket'])  
            bucket.objects.filter(Prefix="cost_and_usage/").delete()
            firstOfTheYear = datetime(2020, 1, 1)
            filename_suffix = firstOfTheYear.strftime('%Y-%m-%d')+"-"+firstOfLastMonth.strftime('%Y-%m-%d')
            renderCosts(accountItem, firstOfTheYear.strftime('%Y-%m-%d'), firstOfLastMonth.strftime('%Y-%m-%d'), filename_suffix)
            response = table.update_item(
                Key={
                    'accountid': accountItem['accountid']
                },
                UpdateExpression="set first_import = :r",
                ExpressionAttributeValues={
                    ':r': 'false',
                },
                ReturnValues="UPDATED_NEW"
            )  
            logger.info("table.update_item: {}".format(response))            
                            
        renderCosts(accountItem, firstOfLastMonth.strftime('%Y-%m-%d'), firstOfThisMonth.strftime('%Y-%m-%d'), firstOfLastMonth.strftime('%Y-%m'))
        enddate = secondOfThisMonth.strftime('%Y-%m-%d') if firstOfThisMonth.strftime('%Y-%m-%d') == today.strftime('%Y-%m-%d') else today.strftime('%Y-%m-%d')
        renderCosts(accountItem, firstOfThisMonth.strftime('%Y-%m-%d'), enddate, today.strftime('%Y-%m'))
        writeManifestFiles(accountItem)


def writeManifestFiles(accountItem):
    for group_type in param_objects.keys():
        json_d = json.load(open('manifest.json', 'r'))
        json_string = json.dumps(json_d)
        json_string= json_string.replace("<ACCOUNT_ID>",accountItem['accountid']).replace("<GROUP_TYPE>",group_type)
        with open("/tmp/manifest.json", 'w+') as file:
            file.write(json_string)
            file.close()
        json_binary = open('/tmp/manifest.json', 'rb').read()
        s3_client.put_object(ACL='bucket-owner-full-control',Body=json_binary, ContentType='application/json', Bucket=accountItem['bucket'], Key='cost_and_usage/'+group_type+'/manifest.json') 
    
def renderCosts(accountItem, start, end, filename_suffix):
    logger.info("accountid: {}, start: {},end: {},filename_suffix: {}".format(accountItem['accountid'],start,end,filename_suffix))
    accountIds = [accountItem['accountid']] + accountItem['additional_accountsids']
    resultsAllAccounts = {}
    
    for group_type, param_obj in param_objects.items():
        for accountId in accountIds:
            results = []
            token = None
            while True:
                if token:
                    kwargs = {'NextPageToken': token}
                else:
                    kwargs = {}
                data = ce_client.get_cost_and_usage(
                    TimePeriod={'Start': start, 'End':  end}, 
                    Granularity='DAILY', 
                    Filter = {
                        "And": [{
                            "Dimensions": {
                                "Key": "LINKED_ACCOUNT",
                                "Values": [accountId]
                            }
                        }, {
                            "Not": {
                                "Dimensions": {
                                    "Key": "RECORD_TYPE",
                                    "Values": ["Credit", "Refund","Tax"]
                                }
                            }
                        }]
                    },       
                    Metrics=['UnblendedCost'], 
                    GroupBy=[{'Type': param_obj['groupby_1_type'], 'Key': param_obj['groupby_1_key']}, {'Type': param_obj['groupby_2_type'], 'Key': param_obj['groupby_2_key']}], 
                    **kwargs
                )
                logger.debug("data: {}".format(data))
                results += data['ResultsByTime']
                token = data.get('NextPageToken')
                if not token:
                    break
            resultsAllAccounts[accountId] = results
        uploadData(resultsAllAccounts, param_obj['labels'], accountItem['bucket'], 'cost_and_usage/'+group_type+'/data_'+filename_suffix+'.tsv')

def uploadData(data, labels, bucketname, bucketkey):
  logger.debug("uploadData: {}".format(data))
  with open("/tmp/data.tsv", "w") as file:
      csv_file = csv.writer(file, delimiter='\t')
      csv_file.writerow(['TimePeriod','Accountid',labels[0],labels[1],'Amount','Unit'])
      #for result_by_time in data:
      for accountid, accountData in data.items():
        for result_by_time in accountData:
            logger.debug("bucketname: {}, start: {}, len(groups): {}".format(bucketname, result_by_time['TimePeriod']['Start'], len(result_by_time['Groups'])))  
            for group in result_by_time['Groups']:
                amount = group['Metrics']['UnblendedCost']['Amount']
                unit = group['Metrics']['UnblendedCost']['Unit']
                writerow_return = csv_file.writerow([result_by_time['TimePeriod']['Start'],accountid,group['Keys'][0],group['Keys'][1],amount, unit])
                logger.debug("service: {}, csv_file: {}".format(group['Keys'][1],writerow_return))
  
  csv_binary = open('/tmp/data.tsv', 'rb').read()
            
  return_s3_upload = s3_client.put_object(ACL='bucket-owner-read',Body=csv_binary, ContentType='text/tsv', Bucket=bucketname, Key=bucketkey)
  logger.info("s3_client.put_object - bucketname: {}, bucketkey: {}".format(bucketname,bucketkey))     
  return True  
      