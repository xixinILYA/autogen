import requests
import json


def get_cpu_mem_usage(ip):
    url = "http://opdproxy.kgidc.cn/b-monitor-metricqueryapi/v1/query?opdAppid=v1-642250a7e5a9a"
    headers = {'Content-Type': 'application/json'}

    data1 = {"metric": f"quantile_over_time(0.90,new_cpu_avg{{ip=\"{ip}\"}}[7d])"}
    data2 = {"metric": f"quantile_over_time(0.90,new_mem_ratio{{ip=\"{ip}\"}}[7d])"}

    response1 = requests.post(url, headers=headers, data=json.dumps(data1))
    response2 = requests.post(url, headers=headers, data=json.dumps(data2))

    tmp1, tmp2 = response1.json(), response2.json()

    cpu_usg = format(float(tmp1["data"][-1]["value"][1]), ".2f") if tmp1['data'] else 'F'
    mem_usg = format(float(tmp2["data"][-1]["value"][1]), ".2f") if tmp2['data'] else 'F'

    return cpu_usg, mem_usg
def get_hardware_specs(ip):
    url = "http://opdproxy.kgidc.cn/b-monitor-metricqueryapi/v1/query?opdAppid=v1-642250a7e5a9a"
    headers = {'Content-Type': 'application/json'}

    data1 = {"metric": f"avg(res_vol{{ip=\"{ip}\",useType=\"cpu\"}})[1h]"}
    data2 = {"metric": f"avg(res_vol{{ip=\"{ip}\",useType=\"mem\"}})[1h]"}

    response1 = requests.post(url, headers=headers, data=json.dumps(data1))
    response2 = requests.post(url, headers=headers, data=json.dumps(data2))

    tmp1, tmp2 = response1.json(), response2.json()

    cpu_hardware = tmp1["data"][0]["values"][0][1] if tmp1['data'] else 'F'
    mem_hardware = tmp2["data"][0]["values"][0][1] if tmp2['data'] else 'F'

    return cpu_hardware, mem_hardware
def get_machine_info(ip):
    url = "http://opdproxy.kgidc.cn/b-cmdb-common/v1/base_property/get_data/machine_base"

    payload = {
        "associationProperty": "OPD::CMDB::base_property::machine_base",
        "filter": [
            {
                "field": "sship",
                "operator": "in",
                "prefix_combine": "or",
                "value": [ip]
            }
        ],
        "groupby": [],
        "limit": "1",
        "offset": "0",
        "opdAppid": "{{sk.cvmopdAppid}}",
        "opdAppsecret": "{{sk.cvmopdAppsecret}}",
        "order": [],
        "tbprefix": "",
        "tbsuffix": ""
    }

    headers = {
        'Content-Type': 'application/json'
    }

    response = requests.post(url, headers=headers, json=payload)
    tmp = response.json()
    machinetype=tmp['data'][0]['machineType'] if tmp['data'] else 'F'
    machineclass=tmp['data'][0]['machineClass'] if tmp['data'] else 'F'
    return machinetype,machineclass


def exe_dify():
    data = {
        "inputs": {
            "cpu": "32",
            "mem": "64",
            "cpu_precent": "5.87",
            "mem_precent": "43.21",
            "machine_type": "CVM_TX",
            "machine_specification": "S5.8XLARGE64"
        },
        "response_mode": "blocking",
        "user": "pipeline"
    }

    headers = {
        'Host': 'dify.opd.kugou.net',
        'Authorization': 'Bearer app-0E73Ys4ywhawXOM7LmiGgVqa',
        'Content-Type': 'application/json'
    }

    response = requests.post('http://dify.opd.kugou.net/v1/workflows/run', headers=headers, json=data)

    ret = {}
    if response.status_code != 200:
        ret["error"] = str(response.content)
        return (ret,1)
    else:
        return (response.json(),0)

if __name__ == "__main__":
    # cpu_usg, mem_usg = get_cpu_mem_usage(sship)
    # cpu_hardware, mem_hardware = get_hardware_specs(sship)
    # machine_type,machine_class= get_machine_info(sship)
    ret,flag=exe_dify()
    if flag==0:
        ret_str = json.dumps(ret, ensure_ascii=False)
        ret_dict = json.loads(ret_str)
        outputs = ret_dict["data"]["outputs"]
        result = outputs["result"]
        s_machine = outputs["s_machine"]
        d_machine = outputs["d_machine"]
        deailt_result = outputs["deailt_result"]
        # print("当前IP:",sship)
        print("当前机型:", s_machine)
        print("目标机型:", d_machine)
        print("\n")
        print("ai分析:", result)
        print("\n")
        print("ai分析详情:", deailt_result)
    else:
        print(ret)















 