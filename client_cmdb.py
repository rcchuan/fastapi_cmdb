from datetime import datetime
import json
import platform
import socket
import time

import distro
import psutil
import requests



# 1 获取服务器ip地址
# python有模块 socket Python 内置的网络通信核心模块
# 这个场景里，用 UDP 不是为了通信，而是为了“骗”操作系统选出一个本机 IP。 用 TCP 也行，但 UDP 更轻。
# 用 UDP 不是因为要 UDP 通信，而是因为：
# UDP connect 不发包、不握手，只是让内核选路由，确定本机 IP。
# TCP connect 要三次握手，网络不通会超时，拿 IP 失败。
# 这个场景只要“选路由”，不需要“建立连接”，所以 UDP 更轻、更稳。
def get_ip():
  # 创建一个 IPv4 的 UDP 套接字。
  s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
  s.connect(("8.8.8.8",80))
  info=s.getsockname()
  ip=info[0]
  s.close()
  return ip



# 2 获取当前服务器的操作系统信息
# python有模块distro，获取操作系统等相关的信息
# python有模块platform
def get_os_info():
  release_info = distro.distro_release_info()
  return{
    # 操作系统版本
        "os_version": platform.version(),
        "os_arch": platform.machine(),
        "os_type": platform.system(),
        "distribution_name": distro.name(),
        "distribution_version": release_info.get("version_id", "")
  }

# 3 获取磁盘信息
    # python模块psutil实现
    # 获取服务器所有磁盘分区
def get_disk():
  # 定义列表，封装数据使用的
  partitions =[]
  all_disk = psutil.disk_partitions(all=True)
    # 遍历所有磁盘分区，得到每个磁盘，
    # 获取每个磁盘详细信息，比如名称，大小，类型等
  for disk in all_disk:
    usage= psutil.disk_usage(disk.mountpoint)
    partitions.append({
      "device": disk.device, # 磁盘路径  c  d
            "mountpoint": disk.mountpoint, # 挂载
            "total": usage.total,
            "used": usage.used,
            "free": usage.free,
            "fstype": disk.fstype, # 类型
            "opts": disk.opts, # rw 读写
    })
  return partitions


# 4 获取node_exporter端口号
NODE_EXPORTER_DEFAULT_PORT = 9100  # 默认端口
#运维脚本要连本机的 node_exporter，但端口不固定，所以先遍历进程，从启动命令里解析出真实端口返回,没有就返回默认值。
def get_node_exporter_port():
  # 获取所有进程判断
  for proc in psutil.process_iter(["pid", "name", "cmdline"]):
    if ("node_exporter" in proc.info["name"]
      or
      "node_exporter" in str(proc.info["cmdline"])):
      cmdline = proc.info["cmdline"]
      for arg in cmdline:
                if arg.startswith("--web.listen-address="):
                    # --web.listen-address=:9101
                    return int(arg.split(":")[-1])
  return NODE_EXPORTER_DEFAULT_PORT

# 统一获取所有信息的方法
def collect():
   # 规范：设置当前发行版本号
   distro.major_version()
   hostname = socket.gethostname()
   return{
        "cpu_count": psutil.cpu_count(logical=True),
        "mem_total": psutil.virtual_memory().total,
        "hostname": hostname,
        "ip": get_ip(),
        "disk": get_disk(),
        "os_info" : get_os_info(),
        "node_exporter_port": get_node_exporter_port(),
        "server_info": socket.gethostname()
   }


# 上报服务器端
# 服务器接收数据的接口路径和提交方式
SERVER_URL = "http://127.0.0.1:8001/api/v1/host/report"
# post提交方式
# python有模块 requests，实现发送请求过程
# os_info上报给服务器数据
def report_to_server(os_info):
    # 非空判断
    if not os_info:
        return False
    # 不为空 ，发送post请求，请求服务器端接口
    try:
        #把os_info通过 HTTP POST 请求，上报给服务端。然后用response变量来接受响应的json
        response = requests.post(
            SERVER_URL,  # post请求接口路径
            json=os_info, # 向接口传递数据
            timeout=10
        )
        # 两层判断，一层看 HTTP，一层看业务。根据服务器返回response判断成功 失败
        # 看 HTTP: raise_for_status内置方法，判断响应状态码是否200;2xx：不报错，继续往下。4xx、5xx：抛异常，跳到 except，返回失败。
        response.raise_for_status()

        # 看业务返回码:获取服务器端返回数据
        result = response.json()
        # 如果code ==0 成功
        if result["code"] == 0:
            print(f"上报成功")
            return True
        else:
            print(f"上报失败")
            return False
    except Exception as e:
        print(f"上报请求失败：{e}\n")
        return False     
     





if __name__ == '__main__':
    # 定期上报这些信息给服务器端
    # 每10s上报一次
    # 死循环 + sleep实现  
  while True:
     print(f"开始上报资产信息（{datetime.now()}）")
     all_info = collect()
     print(json.dumps(all_info, indent=4, ensure_ascii=False))
     #上报服务器端
     report_to_server(all_info)

     # 睡10s
     time.sleep(10)