# coding: utf-8

from pathlib import Path
import salt.client
import conf.deploy as deploy_conf
from datetime import datetime
import subprocess
import logging
# import tail
import select
import time
import threading, thread

"""
类设计思路：

1、部署的包分成三类：
    Jar包
    Common War包（CWAR）
    Admin War包（AWAR）


2、首先定义部署包的基类 BasePackage，其中包含了几个主要操作方法和常规属性，
    接着分别定义 Jar包类 JARPackage 和 War包基类 WARPackage，均继承自BasePackage，
    最后是 Common War 和 Admin War 的类，继承自 WARPackage
    这两个类主要做的是定义自己内部的几个路径变量

    继承关系如下图：

            BasePackage
                |
         |--------------|
    JARPackage      WARPackage
                        |
                 |--------------|
            CWARPackage       AWARPackage


3、基本思想：尽可能将通用的属性和方法集中在基类中，子类中各自实现自定义功能。

    不同类型的包在部署流程上大同小异，
        流程是：备份旧包 --> 拷贝新包到远程主机 --> 新包替换旧包 --> （jar包服务重启）

    所不同的是每种类型的包对应的几个路径，其中涉及到的路径有一下几个：
        1）新包从svn上下载到本地后的路径，
        2）新包上传到目标主机的路径，
        3）旧包的备份路径，
        4）包的运行路径，

    以上四个路径对应的变量以及 “包含文件名” 的完整路径变量对应关系如下：
        1）SALT_SVN_PATH                   <==> SVN_FILE
        2）DIR_SRC                         <==> SRC_FILE
        3）JAR_BACKUP_DIR(WAR_BACKUP_DIR)  <==> BACKUP_FILE
        4）JAR_DIR_DEST(WAR_DIR_DEST)      <==> DEST_FILE

    *注：以上右边四个变量除了 SVN_FILE 是字符串str，其它都是 Path 类的实例。
            SVN_FILE 因为要通过 saltstack 上传文件， 所以路径不是标准的文件系统路径，
            而是类似于 salt://svn_package/jar/xxx.jar, 其对应到文件系统中的路径是 /srv/salt/svn_package/jar/xxx.jar
"""

class BasePackage(object):

    def __init__(self, name, server_ip):

        self.name = name
        self.server_ip = server_ip.split(',')

        self.start_time = datetime.now()
        self.now_str = self.start_time.strftime(deploy_conf.BACKUP_DIR_TIME_FORMAT)

        self.SRC_FILE = Path(deploy_conf.DIR_SRC).joinpath(self.name)

        self.salt_client = salt.client.LocalClient()

        self._ping_target()

        # print "BasePackage init {}".format(self.__class__.__name__)

        self.LOGFILE = Path("/tmp").joinpath(self.name + ".log")

        self._init_log_watcher()
        self.log_str = "init log"
        self.log_list = []


        # logging.basicConfig(filename = str(self.LOGFILE), level = logging.INFO)


    def _init_log_watcher(self):
        self.log_watcher = subprocess.Popen('tailf -0 ' + str(self.LOGFILE), stdout = subprocess.PIPE, stderr = subprocess.PIPE, shell = True)

        # self.log_watcher = threading.start_new_thread(self._append_log)
        self.watch_log_thread = threading.Thread(target = self._append_log)
        self.watch_log_thread.start()

        # self.tail = tail.Tail(str(self.LOGFILE))
        # self.tail.register_callback(self._append_log)

        # self._poll = select.poll()
        # self._poll.register(self.log_watcher)

    # def _append_log(self, line):
    #     print "append to log: ", line
    # def _append_log(self, line):

    def _append_log(self):
        print "==============starting thread"
        count = 3

        # while True:
        #     print "=============reading..."
        #     line = self.log_watcher.stdout.readline()

        #     if line:
        #         self.log_str += line
        #     else:
        #         time.sleep(3)

        #     count -= 1
        #     if count == 0:
        #         print "===========exit thread"
        #         break

        while True:

            # print self.log_watcher.stdout.readlines()
            # for i in self.log_watcher.stdout.readlines():
            #     print i
            #     self.log_list.append(i)

            
            # time.sleep(3)

            count -= 1
            if count == 0:
                print "===========exit thread"
                # self.watch_log_thread.kill()
                break


    def get_log(self):
        print "=================log str ", self.log_str
        if self.log_str == "":
            self.log_str = self.log_watcher.stdout.read()

        # return self.log_str
        return self.log_list


    def _post_init(self):
        self.salt_client.cmd(self.server_ip, "file.mkdir", [str(self.SRC_FILE.parent)], expr_form = "list")
        self.salt_client.cmd(self.server_ip, "file.mkdir", [str(self.DEST_FILE.parent)], expr_form = "list")
        self.salt_client.cmd(self.server_ip, "file.mkdir", [str(self.BACKUP_FILE.parent)], expr_form = "list")

        self.salt_client.cmd(self.server_ip, "file.touch", [str(self.LOGFILE)], expr_form = "list")
        self.log_handler = open(str(self.LOGFILE), 'a')

        # self.tail.follow(interval = 3, count = 3)


    def _ping_target(self):
        ret = self.salt_client.cmd(self.server_ip, "test.ping", expr_form = "list")
        # print ret

        unreachable_server = list(set(self.server_ip) - set(ret.keys()))
        # print unreachable_server

        if len(unreachable_server) > 0:
            raise Exception("unreachable server {}".format(','.join(unreachable_server)))


    def __del__(self):
        self.log_watcher.kill()



    def backup(self):
        # print self.salt_client.cmd(self.server_ip, 'file.directory_exists', [str(self.BACKUP_FILE.parent)], expr_form = "list")

        # logging.debug("start to backup")
        # print "start to backup"
        self.log_handler.write("{} : start to backup\n".format(datetime.now().strftime(deploy_conf.BACKUP_DIR_TIME_FORMAT)))
        self.log_handler.flush()
        # with open(str(self.LOGFILE), "a") as f:
            # f.write("{} : start to backup\n".format(datetime.now().strftime(deploy_conf.BACKUP_DIR_TIME_FORMAT)))

        # start to backup
        try:
            self.salt_client.cmd(self.server_ip, "file.copy", [str(self.DEST_FILE), str(self.BACKUP_FILE)], expr_form = "list")
        except Exception as e:
            # print(e)
            raise Exception("backup: backup failed!\n" + str(e))
        else:
            return True

    def upload(self):
        # logging.debug("start to upload")
        self.log_handler.write("{} : start to upload\n".format(datetime.now().strftime(deploy_conf.BACKUP_DIR_TIME_FORMAT)))
        self.log_handler.flush()

        try:
            ret = self.salt_client.cmd(self.server_ip, "cp.get_file", [self.SVN_FILE, str(self.SRC_FILE)], expr_form = "list")    
        except Exception as e:
            # print(e)
            raise Exception("upload: upload failed!\n" + str(e))
        else:
            return True

    def replace(self):
        # logging.debug("start to replace")

        try:
            self.salt_client.cmd(self.server_ip, "file.copy", [str(self.SRC_FILE), str(self.DEST_FILE)], expr_form = "list")
        except Exception as e:
            # print(e)
            raise Exception("replace: replace failed!\n" + str(e))
        else:
            return True

    def restart(self):
        pass

    def rollback(self):
        pass
    #     if not self.BACKUP_FILE.exists():
    #         raise Exception("backup file {} not found!".format(str(self.BACKUP_FILE)))

    #     self.salt_client.cmd(self.server_ip, file.copy, [str(self.BACKUP_FILE), str(self.DEST_FILE)], expr_form = "list")


class JARPackage(BasePackage):
    
    def __init__(self, name, server_ip):
        super(JARPackage, self).__init__(name, server_ip)

        self.DEST_FILE = Path(deploy_conf.JAR_DIR_DEST).joinpath(self.name)

        self.SCRIPT_FILE = self.DEST_FILE.with_name(self.name.split("-")[0] + ".sh")  # with_name: Return a new path with the name changed. If the original path doesn’t have a name, ValueError is raised

        self.BACKUP_FILE = Path(deploy_conf.JAR_BACKUP_DIR.format(time = self.now_str)).joinpath(self.name)

        self.SVN_FILE = '{}/jar/{}'.format(deploy_conf.SALT_SVN_PATH, self.name)

        self._post_init()




    def restart(self):
        try:
            self.salt_client.cmd(self.server_ip, "cmd.run", ["sh", str(self.SCRIPT_FILE), "restart"], expr_form = "list")
        except Exception as e:
            # print(e)
            raise Exception("restart: restart failed!\n" + str(e))
        else:
            return True



class WARPackage(BasePackage):

    def __init__(self, name, server_ip):
        super(WARPackage, self).__init__(name, server_ip)

        self.SVN_FILE = '{}/war/{}'.format(deploy_conf.SALT_SVN_PATH, self.name)

        if self.__class__.__name__.startswith("CWAR"):
            DIR_MAP = deploy_conf.CWAR_DIR_MAP
        elif self.__class__.__name__.startswith("AWAR"):
            DIR_MAP = deploy_conf.AWAR_DIR_MAP
        else:
            raise Exception("Class {} undefined!".format(self.__class__.__name__))

        self._dir_index = self._get_dir_index(DIR_MAP, name)

        self.DEST_FILE = Path(deploy_conf.WAR_DIR_DEST.format(dir_index = self._dir_index)).joinpath(self.name)
        self.BACKUP_FILE = Path(deploy_conf.WAR_BACKUP_DIR.format(time = self.now_str, dir_index = self._dir_index)).joinpath(self.name)

        self._post_init()


    def _get_dir_index(self, DIR_MAP, name):
        for i in DIR_MAP.keys():
            if name in DIR_MAP[i]:
                return i


class AWARPackage(WARPackage):
    def __init__(self, name, server_ip):
        super(AWARPackage, self).__init__(name, server_ip)

        

class CWARPackage(WARPackage):
    def __init__(self, name, server_ip):
        super(CWARPackage, self).__init__(name, server_ip)
