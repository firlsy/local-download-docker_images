#!/usr/bin/env python3
import os
import sys
import argparse
import subprocess
from datetime import datetime, timedelta
import configparser
import re
import zipfile
import shutil

CONFIG_FILE = "config_docker-downlocal.conf"
DOCKER_CLI = "docker"

class DockerImageManager:
    def __init__(self):
        self.config = None
        self.remote_path = ""
        self.registry_mirrors = []
        self.image_info = {
            'original_name': '',
            'original_tag': 'latest',
            'arch': 'amd64',
            'mirror': None,
            'tar_name': '',
            'zip_name': '',
            'pulled_ref': ''
        }

    def handle_config(self):
        """处理配置文件"""
        if not os.path.exists(CONFIG_FILE):
            self.create_config_template()
            print(f"\n配置文件已创建：{os.path.abspath(CONFIG_FILE)}")
            print("请填写配置后重新运行程序")
            sys.exit(0)
        
        config = configparser.ConfigParser()
        config.read(CONFIG_FILE)
        self.remote_path = config['DEFAULT'].get('remote_path', '/tmp/docker-images')
        self.registry_mirrors = [
            m.strip() for m in 
            config['DEFAULT'].get('registry_mirrors', '').split(',') 
            if m.strip()
        ]

    def create_config_template(self):
        config = configparser.ConfigParser()
        config['DEFAULT'] = {
            'remote_path': '/tmp/docker-images',
            'registry_mirrors': 'https://registry.docker-cn.com,https://mirror.baidubce.com',
            '# 说明': '多个加速地址用英文逗号分隔'
        }
        with open(CONFIG_FILE, 'w') as f:
            config.write(f)

    def parse_image_input(self, image_input):
        """解析镜像输入"""
        if ':' in image_input:
            self.image_info['original_name'], self.image_info['original_tag'] = image_input.split(':', 1)
        else:
            self.image_info['original_name'] = image_input
        
        # 清理特殊字符但保留路径结构
        self.image_info['original_name'] = re.sub(r'[^a-zA-Z0-9_./-]', '_', self.image_info['original_name'])

    def select_architecture(self):
        arch_map = {
            '1': 'amd64',
            '2': 'arm64',
            '3': 'arm/v7'
        }
        print("\n请选择目标架构：")
        for num, arch in arch_map.items():
            print(f"{num}. {arch}")
        
        while True:
            choice = input("请输入序号: ").strip()
            if choice in arch_map:
                self.image_info['arch'] = arch_map[choice]
                return
            print("无效选择，请重新输入")

    def select_mirror(self):
        if not self.registry_mirrors:
            return

        print("\n检测到可用镜像加速器：")
        for i, mirror in enumerate(self.registry_mirrors, 1):
            print(f"{i}. {mirror}")
        print("N. 不使用加速")

        while True:
            choice = input("请选择镜像源（序号/N）: ").strip().lower()
            if choice == 'n':
                return
            if choice.isdigit():
                index = int(choice) - 1
                if 0 <= index < len(self.registry_mirrors):
                    self.image_info['mirror'] = self.registry_mirrors[index]
                    return
            print("无效输入，请重新选择")

    def get_pull_reference(self):
        """构造拉取用的镜像引用"""
        name = self.image_info['original_name']
        if self.image_info['mirror']:
            # 官方镜像处理
            if '/' not in name:
                return f"{self.image_info['mirror']}/library/{name}"
            # 第三方镜像处理
            else:
                return f"{self.image_info['mirror']}/{name}"
        return name

    def check_image_update(self):
        """检查镜像是否需要更新"""
        try:
            # 检查本地镜像
            inspect_cmd = [
                DOCKER_CLI, 'inspect',
                '--format', '{{.Id}}',
                f"{self.get_pull_reference()}:{self.image_info['original_tag']}"
            ]
            result = subprocess.run(
                inspect_cmd,
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                return True

            # 获取远程manifest
            manifest_cmd = [
                DOCKER_CLI, 'manifest', 'inspect',
                f"{self.image_info['original_name']}:{self.image_info['original_tag']}"
            ]
            manifest = subprocess.run(
                manifest_cmd,
                capture_output=True,
                text=True
            )
            if manifest.returncode != 0:
                return True

            # 比较digest
            local_digest = result.stdout.strip().split(':')[1]
            remote_digest = re.search(
                r'"digest":\s*"(\w+:\w+)"', 
                manifest.stdout
            ).group(1)
            return local_digest != remote_digest
            
        except Exception as e:
            print(f"版本检查失败: {str(e)}")
            return True

    def pull_image(self):
        """拉取镜像并修正名称"""
        if not self.check_image_update():
            print("\n本地镜像已是最新版本")
            return

        pull_ref = f"{self.get_pull_reference()}:{self.image_info['original_tag']}"
        platform = f"linux/{self.image_info['arch']}"
        
        cmd = [
            DOCKER_CLI, 'pull',
            '--platform', platform,
            pull_ref
        ]

        print(f"\n正在拉取镜像: {pull_ref}")
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True
        )

        while True:
            output = process.stdout.readline()
            if not output and process.poll() is not None:
                break
            print(output.strip())

        if process.returncode != 0:
            raise RuntimeError("镜像拉取失败")

        # 记录原始拉取引用
        self.image_info['pulled_ref'] = pull_ref

    def rename_image(self):
        """将镜像重命名为原始名称"""
        if not self.image_info['mirror']:
            return

        original_ref = f"{self.image_info['original_name']}:{self.image_info['original_tag']}"
        print(f"\n重命名镜像: {self.image_info['pulled_ref']} -> {original_ref}")
        
        try:
            # 创建新标签
            subprocess.run(
                [DOCKER_CLI, 'tag', self.image_info['pulled_ref'], original_ref],
                check=True
            )
            # 删除旧标签
            subprocess.run(
                [DOCKER_CLI, 'rmi', self.image_info['pulled_ref']],
                check=True
            )
        except subprocess.CalledProcessError as e:
            print(f"镜像重命名失败: {str(e)}")
            raise

        # 更新后续使用的引用
        self.image_info['pulled_ref'] = original_ref

    def generate_filenames(self):
        """生成标准化文件名"""
        safe_name = re.sub(r'[:/]', '_', self.image_info['original_name'])
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_name = f"{safe_name}_{self.image_info['original_tag']}_{self.image_info['arch']}_{timestamp}"
        self.image_info['tar_name'] = f"{base_name}.tar"
        self.image_info['zip_name'] = f"{base_name}.zip"

    def create_tar_package(self):
        """创建原始tar包"""
        print(f"\n正在保存镜像到 {self.image_info['tar_name']}...")
        subprocess.run(
            [DOCKER_CLI, 'save', '-o', self.image_info['tar_name'], self.image_info['pulled_ref']],
            check=True
        )
        print(f"原始tar包已创建，大小: {os.path.getsize(self.image_info['tar_name'])/1024/1024:.2f}MB")

    def compress_to_zip(self):
        """压缩为zip格式"""
        print(f"\n正在创建压缩包: {self.image_info['zip_name']}")
        try:
            with zipfile.ZipFile(self.image_info['zip_name'], 'w', zipfile.ZIP_DEFLATED) as zipf:
                zipf.write(self.image_info['tar_name'], arcname=os.path.basename(self.image_info['tar_name']))
            print(f"压缩完成，压缩包大小: {os.path.getsize(self.image_info['zip_name'])/1024/1024:.2f}MB")
        except Exception as e:
            print(f"压缩失败: {str(e)}")
            raise

    def transfer_zip_file(self):
        """传输zip文件"""
        os.makedirs(self.remote_path, exist_ok=True)
        dest = os.path.join(self.remote_path, self.image_info['zip_name'])
        try:
            shutil.move(self.image_info['zip_name'], dest)
            print(f"\n文件已成功传输至: {dest}")
        except Exception as e:
            print(f"文件传输失败: {str(e)}")
            raise

    def clean_temp_files(self):
        """清理临时文件"""
        if os.path.exists(self.image_info['tar_name']):
            os.remove(self.image_info['tar_name'])
            print(f"已删除临时文件: {self.image_info['tar_name']}")
        if os.path.exists(self.image_info['zip_name']):
            os.remove(self.image_info['zip_name'])
            print(f"已删除临时文件: {self.image_info['zip_name']}")

    def check_container_usage(self):
        """检查镜像是否被使用"""
        result = subprocess.run(
            [DOCKER_CLI, 'ps', '-a', '-q', '--filter', f"ancestor={self.image_info['pulled_ref']}"],
            capture_output=True,
            text=True
        )
        return bool(result.stdout.strip())

    def schedule_cleanup(self):
        """安排24小时后删除镜像"""
        try:
            deletion_time = (datetime.now() + timedelta(hours=24)).strftime("%H:%M %Y-%m-%d")
            cmd = f'echo "{DOCKER_CLI} rmi {self.image_info["pulled_ref"]}" | at {deletion_time}'
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            
            if result.returncode == 0:
                job_id = re.search(r'job (\d+)', result.stdout).group(1)
                print(f"\n已安排24小时后自动清理镜像（任务ID: {job_id}）")
            else:
                print("\n警告：定时任务创建失败，请手动执行以下命令删除：")
                print(f"{DOCKER_CLI} rmi {self.image_info['pulled_ref']}")
                
        except Exception as e:
            print(f"\n定时任务错误: {str(e)}")

    def clean_image(self):
        """清理镜像"""
        if self.check_container_usage():
            print("\n镜像正在使用，保留不删除")
            return

        print("\n执行镜像清理...")
        try:
            subprocess.run(
                [DOCKER_CLI, 'rmi', self.image_info['pulled_ref']],
                check=True
            )
        except subprocess.CalledProcessError:
            print("立即删除失败，转为延迟删除")
            self.schedule_cleanup()

    def run(self):
        parser = argparse.ArgumentParser(description='Docker镜像下载打包工具')
        parser.add_argument('-i', '--image', help='镜像名称（格式: name[:tag]）')
        args = parser.parse_args()

        try:
            self.handle_config()

            if args.image:
                self.parse_image_input(args.image)
            else:
                while True:
                    input_str = input("\n请输入镜像名称（格式: name[:tag]）: ").strip()
                    if input_str:
                        self.parse_image_input(input_str)
                        break

            self.select_architecture()
            self.select_mirror()
            self.pull_image()
            
            if self.image_info['mirror']:
                self.rename_image()
            
            self.generate_filenames()
            self.create_tar_package()
            self.compress_to_zip()
            self.transfer_zip_file()
            
            self.clean_image()
            self.clean_temp_files()

            print("\n" + "="*50)
            print(f"""使用说明：
1. 在目标机器执行：
   unzip {os.path.basename(self.image_info['zip_name'])}
   docker load -i {self.image_info['tar_name']}

2. 验证镜像：
   docker images | grep {self.image_info['original_name'].replace('/', '_')}""")

        except KeyboardInterrupt:
            print("\n操作已取消")
            self.clean_temp_files()
            sys.exit(130)
        except Exception as e:
            print(f"\n[错误] {str(e)}")
            self.clean_temp_files()
            sys.exit(1)

if __name__ == "__main__":
    DockerImageManager().run()
