import os
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel
import uvicorn
from fastapi import Depends, FastAPI
from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, Integer, String, create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session, declarative_base, relationship, sessionmaker
from sqlalchemy.exc import SQLAlchemyError
from starlette.requests import Request
from starlette.responses import HTMLResponse
from starlette.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates

# fastapi创建
app = FastAPI(title="CMDB 配置管理系统",version=1.0)

# 设置对外访问接口路径+提交方式
@app.get("/api/v1/healthy",summary="健康检查")
def healthy():
    return {"code":0,"status":"ok"}


#################1 操作mysql#######################
# 创建基类
Base = declarative_base()

# 主机hosts  和  磁盘disks 关系一对多关系 在磁盘表创建字段作为外键
# 1. 一个主机有多个磁盘，一个磁盘属于一个主机
# 这是典型的一对多关系。数据库层面，外键 host_id 放在 Disk 表里（“多”的一方）。但在 ORM 层面，你希望两个方向都能查：
# 从 Host 查：host.disks → 得到这个主机的所有磁盘     从 Disk 查：disk.hosts → 得到这个磁盘属于哪个主机

# 2. relationship() 就是用来建立这种“对象级关联”的     它告诉 SQLAlchemy：“这两个类之间有关系，查一个的时候顺便能拿到另一个。”

# 3. back_populates 是双向绑定的关键
# back_populates 参数让两个 relationship 互相指向：
# Host.disks 的 back_populates="hosts" 指向 Disk.hosts      Disk.hosts 的 back_populates="disks" 指向 Host.disks
# 这样 SQLAlchemy 就知道：“这两个关系是同一段关系的两个方向，要同步维护。”


# 创建实体类
# 主机 hosts
class Host(Base):
    # 对应表名
    __tablename__ ="hosts"
    # 其他字段
    # 属性名词 = 类型 + 约束等
    id = Column(Integer, primary_key=True, autoincrement=True,comment="主键id")
    ip = Column(String(50),comment="ip地址",unique=True)

    hostname = Column(String(50), comment="主机名")
    mem_total = Column(BigInteger, comment="总内存")
    cpu_count = Column(Integer, comment="CPU 核心数")
    node_exporter_port = Column(Integer, comment="node_exporter 端口")
    distribution_name = Column(String(50), comment="发行版名称")
    distribution_version = Column(String(50), comment="发行版版本")
    os_version = Column(String(200), comment="操作系统版本")
    os_arch = Column(String(20), comment="操作系统架构（如 x86_64）")
    os_type = Column(String(50), comment="操作系统类型")
    environment = Column(String(50), comment="环境")
    region = Column(String(50), comment="区域")
    provider = Column(String(50), comment="提供商")
    service_type = Column(String(50), comment="服务类型")
    business = Column(String(50), comment="业务线")
    serial = Column(String(50), comment="序列号")
    op_group = Column(String(50), default="", comment="运维组")
    dev_group = Column(String(50), default="", comment="开发组")
    tags = Column(String(512), default="", comment="标签")
    enabled = Column(Boolean, default=True, comment="是否启用")

    report_time = Column(DateTime, default=datetime.now, comment="上报时间")
    create_time = Column(DateTime, default=datetime.now, comment="首次创建时间")
    update_time = Column(DateTime, default=datetime.now, onupdate=datetime.now, comment="最后更新时间")

    # 一个主机有多个磁盘
    # relationship(关联实体类名称，关联的实体类对应属性名称，是否级联)
    disks = relationship("Disk", back_populates="hosts",cascade="all, delete")
    

# 磁盘 disk
class Disk(Base):
    """MySQL 数据表对应的 ORM 模型（表名：cmdb_disk）"""
    __tablename__ = "disks"
    id = Column(Integer, primary_key=True, comment="ID")
    device = Column(String(255), comment="设备名称")
    mountpoint = Column(String(50), comment="挂载点")
    fstype = Column(String(50), comment="文件系统类型")
    total = Column(BigInteger, comment="总大小")
    opts = Column(String(255), comment="挂载选项")
    # 外键
    # ForeignKey("外键关联表名称.关联字段主键")
    host_id = Column(Integer, ForeignKey("hosts.id"), comment="关联主机ID")

    # 一个磁盘属于某个主机
    # relationship(关联实体类名称，关联的实体类对应属性名称，是否级联)
    hosts = relationship("Host", back_populates="disks")


#################2 从代码反向生成数据库结构#######################
# 执行前：数据库 cmdb 存在，但里面没有 host 和 disk 表。
# 执行 create_tables() 后：
# 如果表不存在 → 自动创建 host 和 disk 表    如果表已存在 → 不报错，跳过创建  控制台打印“数据表创建成功（或已存在）”

# 原理：继承了 Base 的类，在定义时被 SQLAlchemy 的元类拦截，从中提取出表结构，组装成 Table 对象，注册到 Base.metadata.tables 里，create_all 连库检查后，只对不存在的表执行 CREATE TABLE。

# 定义数据库连接信息
MYSQL_CONFIG = {
    "host": os.getenv("CMDB_DB_HOST", "127.0.0.1"),
    "port": int(os.getenv("CMDB_DB_PORT", "3306")),
    "user": os.getenv("CMDB_DB_USER", "cmdb"),
    "password": os.getenv("CMDB_DB_PASSWORD", ""),
    # 提前创建数据库 cmdb
    "db": os.getenv("CMDB_DB_NAME", "cmdb"),
    "charset": "utf8mb4",
}
# 建立数据库连接  orm
# 使用 URL.create，避免密码中的特殊字符破坏连接地址
DATABASE_URL = URL.create(
    "mysql+pymysql",
    username=MYSQL_CONFIG["user"],
    password=MYSQL_CONFIG["password"],
    host=MYSQL_CONFIG["host"],
    port=MYSQL_CONFIG["port"],
    database=MYSQL_CONFIG["db"],
    query={"charset": MYSQL_CONFIG["charset"]},
)
engine = create_engine(
    DATABASE_URL, # 连接地址，必须有的
    echo=False,  # True 会打印 SQL 语句（调试用）
    pool_pre_ping=True, # 检查mysql是否联通
)
# 逆向工程根据实体类创建表
def create_tables():
    try:
        # 调用Base基类封装的方法根据实体类创建表
        Base.metadata.create_all(bind=engine)
        print(f"数据表创建成功（或已存在），表名：{Host.__tablename__}")
        print(f"数据表创建成功（或已存在），表名：{Disk.__tablename__}")
    except SQLAlchemyError as e:
        print(f"数据表创建失败：{e}")
        raise  # 建表失败终止服务

# 调用
# create_tables()

#################3 数据上报接口，获取客户端提交数据，添加mysql里面#######################
# 创建类，用于接收客户端提交过来的数据
# 主机上报接口
class DiskReportRequest(BaseModel):
    device: str
    mountpoint: str
    fstype: str
    opts: str
    total: int

class HostReportRequest(BaseModel):
    ip: str
    hostname: str
    mem_total: int
    cpu_count: int
    node_exporter_port: int
    os_info: dict
    server_info: str
    # 表示一个主机有多个磁盘信息，使用列表
    disk: List[DiskReportRequest]

# 为每次请求创建一次会话连接
SessionLocal = sessionmaker(autocommit=False, autoflush=False,bind=engine)

# 创建生成器方法，每个请求自动获取一个数据库会话，请求结束后自动关闭，不会泄漏连接。
def get_db():
    # 获取会话连接对象
    db = SessionLocal()
    try:
        yield db # 获取db对象之后，做一些事情，之后，执行finally
    finally:
        db.close()

#获取客户端上报过来的数据，如果不存在，直接添加到mysql表，如果存在要对比字段进行更新
@app.post("/api/v1/host/report",summary="数据上报接口")
def report_host(data:HostReportRequest, db: Session = Depends(get_db)):
    # 1 获取客户端上报过来的数据
    # 2 操作主机表
    # 查询当前添加主机在数据库表是否存在  orm
    # select * from hosts h where h.ip=? and h.hostname=?
    host = db.query(Host).filter_by(hostname=data.hostname,ip=data.ip).first()

    # 如果不存在，直接添加到mysql表里面
    if not host:
        # 把添加到hosts表数据设置到host对象里面
        # 创建host对象，设置需要添加值，数据在data里面
        host = Host(
            hostname=data.hostname,
            ip=data.ip,
            cpu_count=data.cpu_count,
            mem_total=data.mem_total,
            os_type=data.os_info.get("os_type", ""),
            os_version=data.os_info.get("os_version", ""),
            os_arch=data.os_info.get("os_arch", ""),
            distribution_name=data.os_info.get("distribution_name", ""),
            distribution_version=data.os_info.get("distribution_version", ""),
            node_exporter_port=data.node_exporter_port,

            environment=data.server_info,
            report_time=datetime.now(),
        )
        db.add(host)
        # autocommit=False, autoflush=False
        # 手动提交  把内存中 --> mysql文件中
        db.commit()
        # 手动刷新  把提交之后的数据更新到内存里面
        db.refresh(host)
    # 如果数据库表 有添加主机信息，判断是否修改数据，比如内存等，进行更新操作
    else:
        # 判断客户端提交数据 和 数据库表数据比较，修改哪些字段值
        # 把需要判断字段放到列表里面，遍历列表得到每个字段，一个字段一个字段比较
        for field in ["hostname", "ip", "cpu_count", "mem_total", "node_exporter_port"]:
            # 根据遍历出来的字段，获取客户端提交过来这个字段对应值（从 data 对象里取名为 field 的属性值）
            # getattr(A, B)：A 是对象，要从谁身上取属性、B 是字符串，要取的属性名
            client_value = getattr(data, field, None)

            # 根据遍历出来的字段，获取数据库表这个字段对应值
            database_value = getattr(host, field)

            # 把这两个值比较
            if client_value != database_value and client_value is not None:
                # 把更新的值，设置到host对象里面,host目前在内存中
                # setattr(host, "cpu_count", 16)
                setattr(host, field, client_value)

        for field in ["os_type", "os_version", "os_arch", "distribution_name", "distribution_version"]:

            value = data.os_info.get(field, None)
            if getattr(host, field) != value and value is not None:
                setattr(host, field, value)

        # host对象有所有需要更新数据
        setattr(host, "report_time", datetime.now())
        db.commit()
        db.refresh(host)

    # 2 操作磁盘表
    # 查询当前添加磁盘在数据库表是否存在
    # 如果不存在，直接添加到mysql表里面
    # 如果添加磁盘信息存在，判断是否修改数据，比如磁盘大小等，进行更新操作
    # 3 特殊情况，比如表里面主机里面磁盘c和d，第二次在这个主机里面添加磁盘，但是只有c，最终删除d

    # 根据 主机id 查询磁盘表，把主机所有磁盘列表查询 []
    all_disklist = db.query(Disk).filter_by(host_id=host.id).all()
    # 把所有磁盘列表遍历，得到每个磁盘，转换字典 {k:v}
    # {}字典里面 value是每个磁盘对象  key是磁盘名称
    # {(c,c挂载):c盘对象,(d,d挂载):d盘对象}
    database_disks = {(d.device, d.mountpoint):d for d in all_disklist}

    # 把客户端提交磁盘数据转换字典
    client_disks = {(d.device, d.mountpoint): d for d in data.disk}

    # 把客户端磁盘字典遍历，得到每个磁盘k-v信息
    for key, new_disk in client_disks.items():
        # 判断客户端提交磁盘在数据库是否存在
        # 数据库没有磁盘，添加
        if key not in database_disks:
            # 创建disk对象，设置添加值
            db.add(Disk(
                host_id=host.id,
                # host_id=os_record.id,
                device=new_disk.device,
                mountpoint=new_disk.mountpoint,
                fstype=new_disk.fstype,
                opts=new_disk.opts,
                total=new_disk.total,
            ))
            db.commit()
        else: # 更新
            disk_record = database_disks[key]

            cur_disk_changed = False
            for field in ["mountpoint", "fstype", "opts", "total"]:

                new_val = getattr(new_disk, field)

                if getattr(disk_record, field) != new_val:
                    setattr(disk_record, field, new_val)
            db.add(disk_record)
            db.commit()

    # 比如第一次在主机id=1下面添加磁盘有c 和  d
    #     第二次还是id=1下面添加磁盘 只有 d
    # 最终效果：数据库表c信息删除
    # 差集实现  A差集B 结果：A里面有B里面没有的
    #              (1,2,3)  - (2,3) = 1
    for key in database_disks.keys() - client_disks.keys():
        db.delete(database_disks[key])
        db.commit()



    # 返回结果
    return {"code": 0, "updated": True}


################# 5 前端调用的数据接口  #######################
# 1 根据条件查询主机信息，比如根据ip地址，根据主机名称等
@app.get("/api/v1/host/search",summary="根据条件搜索主机")
def search_host(q:Optional[str]=None, db: Session = Depends(get_db)):
    # 判断条件值是否为空 ，如果为空查询所有数据，如果不为空根据条件查询
    hosts = db.query(Host)
    # 判断条件 等于空
    if q is None:
        hosts = hosts.all()
    else: # 不为空
        hosts = hosts.filter(
            or_(
                Host.hostname.like(f"%{q}%"),
                Host.environment.like(f"%{q}%")
                )
            ).all()
    for host in hosts:
        # 内存单位 gb
        host.mem_total = round(host.mem_total / 1024 / 1024 / 1024)
        host.mem_total = f"{host.mem_total} GB"

        # 时间格式
        if host.create_time is not None:
            host.create_time = host.create_time.strftime("%Y-%m-%d %H:%M:%S")
        if host.update_time is not None:
            host.update_time = host.update_time.strftime("%Y-%m-%d %H:%M:%S")
        if host.report_time is not None:
            host.report_time = host.report_time.strftime("%Y-%m-%d %H:%M:%S")

    return {"code": 0, "data": hosts}

# 2 修改主机信息
class HostUpdateRequest(BaseModel):
    op_group: Optional[str] = None
    dev_group: Optional[str] = None
    tags: Optional[str] = None
    environment: Optional[str] = None
    region: Optional[str] = None
    provider: Optional[str] = None
    service_type: Optional[str] = None
    business: Optional[str] = None
    serial: Optional[str] = None
# 修改主机信息
@app.post("/api/v1/host/{host_id}", summary="更新主机信息")
def update_host(host_id:int, data:HostUpdateRequest,
                     db: Session = Depends(get_db)):
    try:
        # 根据主机id查询数据库表，如果表没有数据，不进行修改
        hosts = db.query(Host).filter(Host.id == host_id).first()
        if not hosts:
            return {"code": -1, "msg": "数据为空"}
        # 表有数据进行修改
        else:
            for key, value in data.model_dump().items():
                setattr(hosts, key, value)
            db.commit() # 提交
            db.refresh(hosts)
            return {"code": 0, "msg": "更新成功", "data": hosts}
    except SQLAlchemyError as e:
        db.rollback() # 回滚
        return {"code": -1, "msg": "数据错误"}

#禁用主机
@app.post("/api/v1/host/{host_id}/disable", summary="禁用主机")
def disable_host(host_id: int, db: Session = Depends(get_db)):
    """根据os id禁用主机"""
    try:
        host = db.query(Host).filter(Host.id == host_id).first()
        if not host:
            return {"code": -1, "msg": f"ID为 {host_id} 的主机不存在"}
        host.enabled = False
        db.commit()
        db.refresh(host)
        return {"code": 0, "msg": f"主机 {host.ip} 禁用成功", "data": host}

    except SQLAlchemyError as e:
        db.rollback()
        # raise HTTPException(status_code=500, detail=f"数据库操作失败：{str(e)}")
        return {"code": -1, "msg": f"数据库操作失败：{str(e)}"}


#启用主机
@app.post("/api/v1/host/{host_id}/enable", summary="启用主机")
def enable_host(host_id: int, db: Session = Depends(get_db)):
    """根据id启用主机"""
    try:
        host = db.query(Host).filter(Host.id == host_id).first()
        if not host:
            return {"code": -1, "msg": f"ID为 {host_id} 的主机不存在"}
        host.enabled = True
        db.commit()
        db.refresh(host)
        return {"code": 0, "msg": f"主机 {host.ip} 启用成功", "data": host}
    except SQLAlchemyError as e:
        db.rollback()
        # raise HTTPException(status_code=500, detail=f"数据库操作失败：{str(e)}")
        return {"code": -1, "msg": f"数据库操作失败：{str(e)}"}

#####################6 整合前端 ##################################
# html  css  JavaScript   jQuery
# Vue  Reactive uniapp.....
# 挂载静态资源，比如css文件，图片文件等
app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="templates")

@app.get("/",response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(
    request=request,
    name="index.html",
)










if __name__ == "__main__":
    uvicorn.run(app="server_cmdb:app", host="0.0.0.0", port=8001,reload=True)
