Prerequisites
=============

In this demo, we need to have prepare a Ceph Cluster with 3 nodes and a Openstack cluster 3 node . But due to the lack of hardware provides , I 'll use an Openstack AIO (All In One) node instead to represent Openstack cluster .

Infrastructure setup requirements:
    - 3 x Ceph nodes 
    - 1 x Openstack AIO node
    - 1 x Monitor node ( Prometheus + Grafana )
    - 1 x Loki Server node


Ceph Cluster Setup
--------------------
Each node in the cluster must have a unique hostname. Set the hostname on each node accordingly.
Setup Hostname
~~~~~~~~~~~~~~~~~~~

.. code-block:: bash
    sudo hostnamectl set-hostname ceph-node01 # trên node01
    sudo hostnamectl set-hostname ceph-node02  # trên node02  
    sudo hostnamectl set-hostname ceph-node03  # trên node03

Then, update the /etc/hosts file on all nodes to ensure they can resolve each other by hostname.
.. code-block:: bash
    cat << EOF | sudo tee /etc/hosts
    127.0.0.1   localhost
    192.168.198.101 ceph-node01
    192.168.198.102 ceph-node02
    192.168.198.103 ceph-node03

    192.168.198.110 openstack-aio
    192.168.198.111 monitor-node
    192.168.198.112 loki-server
EOF

Verify the hostname configuration on each node:
.. code-block:: bash
    hostname -f


Configure Network
---------------------
Proper network configuration is essential for cluster communication. We'll disable cloud-init network management and set static IP addresses.

On each node:

.. code-block:: bash
    # Disable cloud-init network configuration
    echo "network: {config: disabled}" | sudo tee /etc/cloud/cloud.cfg.d/99-disable-network-config.cfg
    
    # Remove cloud-init generated files
    sudo rm -f /etc/netplan/50-cloud-init.yaml
    sudo rm -f /etc/netplan/90-installer-network.yaml
    sudo cloud-init clean --logs

    # Configure network interfaces
    cat << EOF | sudo tee /etc/netplan/01-netcfg.yaml
    network:
        version: 2
        renderer: networkd
        ethernets:
        ens33:                  
            addresses:
            - 192.168.198.101/24  # [REPLACE WITH YOUR NODE'S IP]
            routes:
            - to: default
                via: 192.168.198.2   
            nameservers:
            addresses:
                - 8.8.8.8
            dhcp4: false            
        ens34:                  
            dhcp4: false
            optional: true
    EOF

    # Apply configuration
    sudo chmod 600 /etc/netplan/01-netcfg.yaml
    sudo netplan apply

    # Test connectivity
    ping -c2 ceph-node02
    ping -c2 ceph-node03

After applying these changes, verify that all nodes can communicate with each other.

Prepare Disks and Disable Swap
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Ceph OSDs require dedicated disks. We'll prepare additional disks and disable swap to ensure optimal performance.

.. code-block:: bash
    # Disable swap - Ceph requires swap to be disabled
    sudo swapoff -a
    sudo sed -i.bak -r 's|(^[^#].*swap.*)|#\1|' /etc/fstab
    # Verify available disks
    lsblk
    # Clean additional disks for OSD use (example: /dev/sdb)
    # WARNING: This will erase all data on the disk
    sudo wipefs -a /dev/sdb
    sudo sgdisk --zap-all /dev/sdb


Install Required Packages
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Install essential packages including Docker, which Ceph will use for containerized deployment.

Thực hiện trên các node :
.. code-block:: bash
    # Update package lists and upgrade existing packages
    sudo apt update && sudo apt upgrade -y

    # Install basic dependencies
    sudo apt install -y python3 python3-pip podman vim htop lvm2 net-tools chrony curl openssh-server

    # Install Docker
    sudo mkdir -p /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

    sudo apt update && sudo apt install -y docker-ce docker-ce-cli containerd.io

    # Verify Docker installation
    sudo docker version
    sudo docker info

### Setup Firewall

Áp dụng tất cả các node :

```bash
# Cài đặt nếu chưa có 
sudo apt install -y ufw

# Kiểm tra trạng thái
sudo ufw status verbose

## Reset về trạng thái mặc định nếu trước đó có setup
sudo ufw --force reset

# Mặc định deny tất cả inbound, allow outbound
sudo ufw default deny incoming
sudo ufw default allow outgoing

sudo ufw allow 22/tcp comment 'SSH Access'
sudo ufw allow 6789/tcp comment 'Ceph MON'
sudo ufw allow 8443/tcp comment 'Ceph MGR Dashboard'
sudo ufw allow 9283/tcp comment 'Ceph MGR Prometheus metrics'
sudo ufw allow 6800:7300/tcp comment 'Ceph OSDs'
sudo ufw allow 3000/tcp comment 'ceph Grafana Dashboard'
sudo ufw allow 5000/tcp comment 'Ceph REST API'
sudo ufw allow 7480/tcp comment 'Ceph RGW'
sudo ufw allow 3300/tcp comment 'Ceph MON quorum'
sudo ufw allow 9100/tcp comment 'Node exporter metrics'

sudo ufw allow from 192.168.198.0/24 comment 'Cluster network traffic'


# Enable và kiểm tra
sudo ufw enable
sudo ufw status verbose
```

### Setup NTP ( Network Time Protocol ) - Đồng bộ thời gian

```bash
# Đồng bộ thời gian chính xác
sudo systemctl enable --now docker chrony ssh
```

### **Cấu hình SSH keyless for root**

```bash
# Tạo ssh key trên node01 (lưu ý: dùng đường dẫn tuyệt đối đến /root/.ssh)
sudo rm -rf /root/.ssh
sudo mkdir -p /root/.ssh
sudo ssh-keygen -t ed25519 -N "" -f /root/.ssh/id_ed25519
# Nếu cần tương thích ngược, chỉ tạo RSA thay cho ED25519
# sudo ssh-keygen -t rsa -b 4096 -N "" -f /root/.ssh/id_rsa

# Quyền thư mục / file -node 1
sudo chown root:root /root/.ssh
sudo chmod 700 /root/.ssh
sudo chmod 600 /root/.ssh/id_ed25519
sudo chmod 644 /root/.ssh/id_ed25519.pub

# Tạm bật password root (nếu cần) để dễ thao tác rồi tắt sau khi xác nhận keyless
# (chỉ chạy nếu bạn chưa set password root)
sudo passwd root

# Cho phép root login bằng password (tạm thời trên cả 3 node)
sudo sed -i 's/^#*PermitRootLogin.*/PermitRootLogin yes/' /etc/ssh/sshd_config
sudo sed -i 's/#PasswordAuthentication yes/PasswordAuthentication yes/g' /etc/ssh/sshd_config
sudo sed -i 's/PasswordAuthentication no/PasswordAuthentication yes/g' /etc/ssh/sshd_config
sudo systemctl restart ssh


# Clean fingerprint
ssh-keygen -R node2.ceph.local
ssh-keygen -R node3.ceph.local
ssh-keygen -R node4.ceph.local

# Copy public key tới các node (gộp 1 lần, chỉ dùng id_ed25519.pub) - node01
sudo ssh-copy-id -i /root/.ssh/id_ed25519.pub root@node2.ceph.local
sudo ssh-copy-id -i /root/.ssh/id_ed25519.pub root@node3.ceph.local
sudo ssh-copy-id -i /root/.ssh/id_ed25519.pub root@node4.ceph.local



# Kiểm tra keyless login
ssh -o StrictHostKeyChecking=no root@node2.ceph.local 'hostname -f; whoami'
ssh -o StrictHostKeyChecking=no root@node3.ceph.local 'hostname -f; whoami'

# Sau khi xác nhận keyless hoạt động: vô hiệu hoá password authentication (tất cả node)
sudo sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
sudo sed -i 's/^#*PermitRootLogin.*/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config
sudo systemctl restart ssh

# Kiểm tra trạng thái thời gian / đồng bộ
timedatectl status
sudo systemctl status chrony
```

## Bootstrap Ceph Cluster 
sudo apt update
sudo apt install -y cephadm

sudo cephadm bootstrap \
    --mon-ip 192.168.198.101 \
    --cluster-network 192.168.198.0/24 \
    --initial-dashboard-user admin \
    --initial-dashboard-password admin123 \
    --allow-fqdn-hostname \


sudo apt update && sudo apt install -y ceph-common

ceph dashboard set-grafana-api-url http://192.168.198.201:3000

# KIỂM TRA sau bootstrap
ceph -s
ceph status
ceph orch host ls



# Kết nối các node
sudo ssh-copy-id -f -i /etc/ceph/ceph.pub root@node2.ceph.local
sudo ssh-copy-id -f -i /etc/ceph/ceph.pub root@node3.ceph.local
sudo ssh-copy-id -f -i /etc/ceph/ceph.pub root@node4.ceph.local

# Kiểm tra lại kết nối (từ node01):
ssh root@node2.ceph.local hostname
ssh root@node3.ceph.local hostname
ssh root@node4.ceph.local hostname

# Thêm các node vào cluster
sudo ceph orch host add node2.ceph.local 192.168.198.102
sudo ceph orch host add node3.ceph.local 192.168.198.103  
sudo ceph orch host add node4.ceph.local 192.168.198.104

# Kiểm tra tổng t
ceph orch host ls
ceph -s

# Disable các cảnh báo ban đầu
sudo ceph config set global mon_warn_on_insecure_global_id_reclaim false
sudo ceph config set global mon_warn_on_insecure_global_id_reclaim_allowed false


## Triển khai dịch vụ Ceph 
sudo ceph orch apply mon --placement "ceph-node01,ceph-node02,ceph-node03"
sudo ceph mon stat

sudo ceph orch apply mgr --placement "ceph-node01,ceph-node02,ceph-node03"
sudo ceph mgr module ls

sudo ceph orch device ls
sudo ceph orch apply osd --all-available-devices
sudo ceph osd tree



## Openstack AIO node Setup

echo "network: {config: disabled}" | sudo tee /etc/cloud/cloud.cfg.d/99-disable-network-config.cfg

## Xóa các file do cloud-init sinh ra
sudo rm -f /etc/netplan/50-cloud-init.yaml
sudo rm -f /etc/netplan/90-installer-network.yaml
## File cấu hình ( tùy chỉnh theo tên card mạng của máy)
cat << EOF | sudo tee /etc/netplan/01-netcfg.yaml
network:
  version: 2
  renderer: networkd
  ethernets:
    ens33:
      addresses:
        - 192.168.198.167/24
      routes:
        - to: 0.0.0.0/0
          via: 192.168.198.2
      nameservers:
        addresses:
          - 8.8.8.8
      dhcp4: false

    ens34:
      dhcp4: false
      optional: true
EOF

sudo chmod 600 /etc/netplan/01-netcfg.yaml
sudo chown root:root /etc/netplan/01-netcfg.yaml


sudo netplan generate
sudo netplan apply


## 2. Chạy lệnh cập nhật

sudo apt update && sudo apt -y upgrade

#Set pasword for all

sudo EDITOR=nano visudo

// Ghi thêm cuối file 

(tên user) ALL=(ALL) NOPASSWD:ALL

sudo apt install python3.12-venv git ceph-common -y

- Tạo thư mục và Python venv
mkdir -p ~/openstack
cd ~/openstack

python3 -m venv .
source bin/activate
python -m pip install --upgrade pip

python -m pip install "ansible-core>=2.15,<2.16"

cd ~/openstack
git clone https://opendev.org/openstack/kolla-ansible
cd kolla-ansible
git fetch --all --tags
git checkout stable/2024.1
python -m pip install .
which kolla-ansible

sudo mkdir -p /etc/kolla
sudo chown $USER:$USER /etc/kolla

cd ~/openstack/kolla-ansible
cp -r etc/kolla/* /etc/kolla


cd openstack
cp ansible/inventory/all-in-one ~/openstack/all-in-one
ls ~/openstack

kolla-genpwd -p /etc/kolla/passwords.yml
sudo chown $USER:$USER /etc/kolla/passwords.yml
sudo chmod 640 /etc/kolla/passwords.yml

sudo nano /etc/kolla/globals.yml
```bash
kolla_base_distro: "ubuntu"
openstack_release: "2024.1"

kolla_internal_vip_address: "192.168.150.149"

network_interface: "ens33"
neutron_external_interface: "ens34"

nova_compute_virt_type: "qemu"

enable_horizon: "yes"
```

cd ~/openstack
source bin/activate

kolla-ansible install-deps

kolla-ansible bootstrap-servers -i ./all-in-one
kolla-ansible prechecks -i ./all-in-one
kolla-ansible deploy -i ./all-in-one

kolla-ansible post-deploy -i ./all-in-one


pip install python-openstackclient -c https://releases.openstack.org/constraints/upper/2025.1


cd /etc/kolla
ls
source /etc/kolla/admin-openrc.sh

cd ~/openstack/kolla-ansible/tools
./init-runonce





## Monitor Node Setup 

## Loki Server Node Setup

