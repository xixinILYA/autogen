import requests
import json
import sys
import argparse
import traceback

kgidc_host = "opdproxy.kgidc.cn"
appid = "v1-66b9ca69ed4f3"
appsecret = "4dbbd4883782f9d0baa29e1f97d82fa8"

def fetch_idc_metrics(rms_id):
    def get_app_running_status():
        url = "http://opdproxy.kgidc.cn/b-cmdb-read/v2/get_app_running_status"
        payload = json.dumps({
            "rmsId": rms_id,
            "opdAppid": appid,
            "opdAppsecret": appsecret
        })
        headers = {'Content-Type': 'application/json'}
        response = requests.post(url, headers=headers, data=payload)
        if response.status_code != 200:
            print(f"Error in get_rms_info: {response}")
            return None
        try:
            return response.json()
        except json.JSONDecodeError:
            print(f"Error in get_app_running_status: JSONDecodeError")
            return None

    def extract_idc_info(data):
        if not data:
            return None
        machines = [i for i in data.get('machineDeployInfo', []) if i.get("role") == 0]
        merged_dict = {}
        for machine in machines:
            idc_name = machine.get("idcCname")
            ip = machine.get("sship")
            if idc_name in merged_dict:
                merged_dict[idc_name]["ipList"].append(ip)
            else:
                merged_dict[idc_name] = {"ipList": [ip]}
        return merged_dict

    def query_metrics(idc_info):
        if not idc_info:
            return None

        url = 'http://opdproxy.kgidc.cn/b-monitor-metricqueryapi/v1/query?opdAppid=v1-67c6a3c68ddb7'
        headers = {'Content-Type': 'application/json'}
        results = []

        for room, data in idc_info.items():
            ip_list = "|".join(data['ipList'])
            metrics = {
                "cpu": f'sum(res_vol{{ip=~"{ip_list}",useType="cpu"}})[1h]',
                "mem": f'sum(res_vol{{ip=~"{ip_list}",useType="mem"}})[1h]'
            }

            room_data = {"zone": room}

            for metric_type, metric_query in metrics.items():
                payload = {"metric": metric_query}
                response = requests.post(url, headers=headers, data=json.dumps(payload))
                if response.status_code != 200:
                    print(f"Error in query_metrics: {response}")
                    return None
                try:
                    response_data = response.json()
                    room_data[metric_type] = response_data['data'][0]['values'][0][1]
                except (KeyError, IndexError, json.JSONDecodeError):
                    print(f"Error in query_metrics: JSONDecodeError")
                    return None

            room_data["ipList"] = data['ipList']
            results.append(room_data)

        return results

    app_data = get_app_running_status()
    idc_info = extract_idc_info(app_data)
    return query_metrics(idc_info) or 'F'


def fetch_cluster_config(rms_id):
    url = "http://opdproxy.kgidc.cn/b-cmdb-read/v2/get_app_cluster_config"
    payload = json.dumps({
        "rmsId": rms_id,
        "opdAppid": appid,
        "opdAppsecret": appsecret
    })
    headers = {'Content-Type': 'application/json'}
    response = requests.post(url, headers=headers, data=payload)
    if response.status_code != 200:
        print(f"Error in fetch_cluster_config: {response}")
        return 'F'

    try:
        data = response.json().get('data', [])
    except json.JSONDecodeError:
        print(f"Error in fetch_cluster_config: JSONDecodeError")
        return 'F'

    clusters = []
    for cluster in data:
        if cluster.get("clusterRole") == "0":
            try:
                num = cluster['expectPodNum']
                clusters.append({
                    'clusterId': cluster['clusterId'],
                    'clusterName': cluster['clusterName'],
                    'pod_cpu_request ': cluster['resources']['request']['cpu'] / 1000,
                    'pod_cpu_limit ': cluster['resources']['limit']['cpu'] / 1000,
                    'pod_mem_request': cluster['resources']['request']['memory'] / 1024,
                    'pod_mem_limit ': cluster['resources']['limit']['memory'] / 1024,
                    'pod_num': num
                })
            except KeyError:
                print(f"Error in fetch_cluster_config: KeyError")
                return 'F'
    return clusters or 'F'


def get_app_risk_rank(rms_id):
    try:
        url = "http://opdproxy.kgidc.cn/b-cmdb-read/v2/get_app_info"
        payload = json.dumps({
            "rmsId": rms_id,
            "opdAppid": appid,
            "opdAppsecret": appsecret
        })
        headers = {'Content-Type': 'application/json'}

        response = requests.post(url, headers=headers, data=payload)
        if response.status_code != 200:
            print(f"Error in get_app_risk_rank: {response}")
            return 'F'

        data = response.json()
        return data["data"]["appBaseInfoData"]["riskRank"]
    except Exception:
        print(f"Error in get_app_risk_rank: Exception")
        return 'F'


def get_k8s_resource_usage(projectid, clusterid):
    url = 'http://opdproxy.kgidc.cn/b-monitor-metricqueryapi/v1/query'
    headers = {'Content-Type': 'application/json'}

    try:
        # 获取 CPU 使用情况
        data_cpu = {
            "metric": f'quantile_over_time(0.95,sum(containerstat_Cpurate{{projectid="{projectid}",clusterid="{clusterid}"}})[7d])/1000'
        }
        response_cpu = requests.post(url, headers=headers, data=json.dumps(data_cpu))
        response_cpu.raise_for_status()
        tmp_cpu = response_cpu.json()
        k8s_cpu_use = round(float(tmp_cpu["data"][0]["value"][1]), 2) if "data" in tmp_cpu and tmp_cpu["data"] else None
    except (requests.RequestException, KeyError, IndexError, ValueError):
        print(f"Error in get_k8s_resource_usage: Exception")
        k8s_cpu_use = None

    try:
        # 获取内存使用情况
        data_mem = {
            "metric": f'quantile_over_time(0.95,sum(containerstat_Memrate{{projectid="{projectid}",clusterid="{clusterid}"}})[7d])/1000'
        }
        response_mem = requests.post(url, headers=headers, data=json.dumps(data_mem))
        response_mem.raise_for_status()
        tmp_mem = response_mem.json()
        k8s_mem_use = round(float(tmp_mem["data"][0]["value"][1]), 2) if "data" in tmp_mem and tmp_mem["data"] else None
    except (requests.RequestException, KeyError, IndexError, ValueError):
        print(f"Error in get_k8s_resource_usage: Exception")
        k8s_mem_use = None

    return k8s_cpu_use, k8s_mem_use


def get_idc_resource_usage(ip_list):
    ip_pattern = "|".join(ip_list)
    url = 'http://opdproxy.kgidc.cn/b-monitor-metricqueryapi/v1/query'
    headers = {'Content-Type': 'application/json'}

    cpu_data = {"metric": f'quantile_over_time(0.90, sum(res_usage{{ip=~"{ip_pattern}", useType="cpu"}})[7d])'}
    mem_data = {"metric": f'quantile_over_time(0.90, sum(res_usage{{ip=~"{ip_pattern}", useType="mem"}})[7d])'}
    cpu_response = requests.post(url, headers=headers, data=json.dumps(cpu_data))
    mem_response = requests.post(url, headers=headers, data=json.dumps(mem_data))

    try:
        cpu_usage = round(float(cpu_response.json()["data"][0]["value"][1]), 2)
    except (KeyError, IndexError, ValueError):
        print(f"Error in get_idc_resource_usage: Exception")
        cpu_usage = None

    try:
        mem_usage = round(float(mem_response.json()["data"][0]["value"][1]), 2)
    except (KeyError, IndexError, ValueError):
        print(f"Error in get_idc_resource_usage: Exception")
        mem_usage = None

    return (cpu_usage, mem_usage)


def fetch_k8s_metrics(projectid, clusterid):
    url = 'http://opdproxy.kgidc.cn/b-monitor-metricqueryapi/v1/query'
    headers = {'Content-Type': 'application/json'}

    def query_metric(metric: str):
        data = {"metric": metric}
        try:
            response = requests.post(url, headers=headers, data=json.dumps(data))
            response.raise_for_status()
            result = response.json()
            if "data" in result and result["data"] and "value" in result["data"][0] and len(
                    result["data"][0]["value"]) > 1:
                return round(float(result["data"][0]["value"][1]), 2)
        except (requests.RequestException, KeyError, IndexError, ValueError):
            print(f"Error in fetch_k8s_metrics: Exception")
            pass
        return None

    cpu_limit = query_metric(f'sum(containerstat_limcpu{{projectid="{projectid}",clusterid="{clusterid}"}})/1000')
    cpu_request = query_metric(f'sum(containerstat_reqcpu{{projectid="{projectid}",clusterid="{clusterid}"}})/1000')
    mem_limit = query_metric(f'sum(containerstat_limmem{{projectid="{projectid}",clusterid="{clusterid}"}})/1000')
    mem_request = query_metric(f'sum(containerstat_reqmem{{projectid="{projectid}",clusterid="{clusterid}"}})/1000')

    return cpu_limit, cpu_request, mem_limit, mem_request


def exe_dify(data_info):
    data = {
        "inputs": {
            "data_info": data_info,
        },
        "response_mode": "blocking",
        "user": "pipeline"
    }

    headers = {
        'Host': 'dify.opd.kugou.net',
        'Authorization': 'Bearer app-EhbX9cVwhoZ7kVrISoYO6c1d',
        'Content-Type': 'application/json'
    }

    response = requests.post('http://dify.opd.kugou.net/v1/workflows/run', headers=headers, json=data)

    ret = {}
    if response.status_code != 200:
        ret["error"] = str(response.content)
        return ret
    else:
        return response.json()


def get_rms_info(rmsId) -> dict:
    rms_id = rmsId
    try:
        idc_metrics = fetch_idc_metrics(rms_id)
        if idc_metrics == 'F':
            idc_metrics = []
        cluster_config = fetch_cluster_config(rms_id)
        if cluster_config == 'F':
            cluster_config = []
        for cluster in cluster_config:
            k8s_cpu_use, k8s_mem_use = get_k8s_resource_usage(rms_id, cluster["clusterId"]) or ('', '')
            cpu_limit, cpu_request, mem_limit, mem_request = fetch_k8s_metrics(rms_id, cluster["clusterId"]) or (
            '', '', '', '')
            if not k8s_cpu_use or not k8s_mem_use or not cpu_limit or not cpu_request or not mem_limit or not mem_request:
                cluster_config.remove(cluster)
            else:
                cluster["cpu_limit"] = cpu_limit
                cluster["cpu_request"] = cpu_request
                cluster["mem_limit"] = mem_limit
                cluster["mem_request"] = mem_request
                cluster["k8s_cpu_use"] = k8s_cpu_use
                cluster["k8s_mem_use"] = k8s_mem_use
        for idc in idc_metrics:
            idc_cpu_use, idc_mem_use = get_idc_resource_usage(idc["ipList"]) or ('', '')
            idc["idc_cpu_use"] = idc_cpu_use
            idc["idc_mem_use"] = idc_mem_use
        rank = get_app_risk_rank(rms_id)
        if rank == 'F':
            rank = ''
        if (idc_metrics or cluster_config) and rms_id and rank :
            ret = {"idc_info": idc_metrics, "k8s_info": cluster_config, "rank": rank, "rmsId": rms_id}
            # ret = json.dumps(ret)
            return {'ret': 0, 'data': ret}
        else:
            missing_fields = []
            if not idc_metrics and not cluster_config:
                missing_fields.append('idc_info,k8s_info')
            if not rank:
                missing_fields.append('rank')
            if not rms_id:
                missing_fields.append('rmsId')
            return {'ret': 1, 'data': '数据未获取成功，未获取成功的数据：' + '，'.join(missing_fields)}
    except Exception as e:
        # 添加异常堆栈信息
        emsg = traceback.format_exc()
        print(f"Error in get_rms_info: {emsg}")
        return {'ret': 1, 'data': '数据未获取成功，错误信息：' + str(e)}


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(description="获取 RMS 信息并格式化输出")
    parser.add_argument("rmsId", type=str, help="RMS ID，例如 9754")
    return parser.parse_args()

if __name__ == "__main__":
    data = {
        "idc_info": [
            {
                "zone": "腾讯云_华北地区_北京",
                "cpu": "64",
                "mem": "128",
                "ipList": [
                    "10.5.140.191",
                    "10.5.140.173"
                ],
                "idc_cpu_use": 16.42,
                "idc_mem_use": 54.9
            }
        ],
        "k8s_info": [
            {
                "clusterId": 63,
                "clusterName": "k8s_cluster_opd_txygzonline",
                "pod_cpu_request ": 2.0,
                "pod_cpu_limit ": 4.0,
                "pod_mem_request": 2.0,
                "pod_mem_limit ": 4.0,
                "pod_num": 1,
                "cpu_limit": 8.0,
                "cpu_request": 4.0,
                "mem_limit": 8.19,
                "mem_request": 4.1,
                "k8s_cpu_use": 1.51,
                "k8s_mem_use": 1.11
            },
            {
                "clusterId": 93,
                "clusterName": "k8s_cluster_opd_txybj6_online_c",
                "pod_cpu_request ": 2.0,
                "pod_cpu_limit ": 5.0,
                "pod_mem_request": 2.0,
                "pod_mem_limit ": 4.0,
                "pod_num": 1,
                "cpu_limit": 30.0,
                "cpu_request": 12.0,
                "mem_limit": 24.58,
                "mem_request": 12.29,
                "k8s_cpu_use": 17.11,
                "k8s_mem_use": 3.87
            }
        ],
        "rank": "P3",
        "rmsId": "10252"
    }

    json_str = json.dumps(data, ensure_ascii=False)

    ret = exe_dify(json_str)

    formatted_json = json.dumps(ret, indent=4, ensure_ascii=False)
    print(formatted_json)

    