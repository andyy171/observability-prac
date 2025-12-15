Prerequisites
=============

In this demo, we need to have prepare a Ceph Cluster with 3 nodes and a Openstack cluster 3 node . But due to the lack of hardware provides , I 'll use an Openstack AIO (All In One) node instead to represent Openstack cluster .

Infrastructure setup requirements:
    - 3 x Ceph nodes 
    - 1 x Openstack AIO node
    - 1 x Monitor node ( Prometheus + Grafana )
    - 1 x Loki Server node


Ceph Cluster Setup
---------------------

Each node in the cluster must have a unique hostname. Set the hostname on each node accordingly.


Setup Hostname
~~~~~~~~~~~~~~~~~~~


.. code-block:: bash
    sudo hostnamectl set-hostname ceph-node01 # trên node01
    sudo hostnamectl set-hostname ceph-node02  # trên node02  
    sudo hostnamectl set-hostname ceph-node03  # trên node03

Then, update the /etc/hosts file on all nodes to ensure they can resolve each other by hostname.

.. code-block:: bash
    cat <<- EOF | sudo tee /etc/hosts
	127.0.0.1 	localhost
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
~~~~~~~~~~~~~~~~~~~
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
            - 192.168.198.102/24 # [REPLACE WITH YOUR NODE'S IP]
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

Configure Firewall
~~~~~~~~~~~~~~~~~~~

Open necessary ports for Ceph services to communicate across the cluster.

Apply in all nodes:

.. code-block:: bash
    # Install UFW (Uncomplicated Firewall) if not present
    sudo apt install -y ufw

    # Check current firewall status
    sudo ufw status verbose

    # Reset to defaults (if previously configured)
    sudo ufw --force reset

    # Set default policies
    sudo ufw default deny incoming
    sudo ufw default allow outgoing

    # Allow required Ceph ports
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

    # Allow cluster network traffic
    sudo ufw allow from 192.168.198.0/24 comment 'Cluster network traffic'

    # Enable firewall and verify configuration
    sudo ufw enable
    sudo ufw status verbose

Configure NTP (Time Synchronization)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Time synchronization is critical for Ceph cluster consistency. Enable and start required services.


.. code-block:: bash
    # Enable required services at boot
    sudo systemctl enable --now docker chrony ssh

Configure SSH Keyless Access for Root
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Passwordless SSH access between nodes is required for Ceph deployment and management.

First, change password for root user on all nodes (if not already set):

.. code-block:: bash
    sudo passwd root

Then, on node01, generate SSH keys and distribute them to other nodes:

.. code-block:: bash

    # Create SSH key for root user
    sudo rm -rf /root/.ssh
    sudo mkdir -p /root/.ssh
    sudo ssh-keygen -t ed25519 -N "" -f /root/.ssh/id_ed25519

    # Set proper permissions
    sudo chown root:root /root/.ssh
    sudo chmod 700 /root/.ssh
    sudo chmod 600 /root/.ssh/id_ed25519
    sudo chmod 644 /root/.ssh/id_ed25519.pub

Temporarily enable password authentication on all nodes to copy SSH keys:

.. code-block:: bash
    # On ALL nodes, enable password authentication temporarily
    sudo sed -i 's/^#*PermitRootLogin.*/PermitRootLogin yes/' /etc/ssh/sshd_config
    sudo sed -i 's/#PasswordAuthentication yes/PasswordAuthentication yes/g' /etc/ssh/sshd_config
    sudo sed -i 's/PasswordAuthentication no/PasswordAuthentication yes/g' /etc/ssh/sshd_config
    sudo systemctl restart ssh

Back on `ceph-node01`:

.. code-block:: bash
    # Remove old SSH fingerprints
    ssh-keygen -R ceph-node02
    ssh-keygen -R ceph-node03

    # Copy SSH public key to other nodes
    sudo ssh-copy-id -i /root/.ssh/id_ed25519.pub root@ceph-node02
    sudo ssh-copy-id -i /root/.ssh/id_ed25519.pub root@ceph-node03

    # Test keyless login
    ssh -o StrictHostKeyChecking=no root@ceph-node02 'hostname -f; whoami'
    ssh -o StrictHostKeyChecking=no root@ceph-node03 'hostname -f; whoami'


- After verifying keyless login works, disable password authentication on all nodes for security:

.. code-block:: bash

    # On ALL nodes, disable password authentication
    sudo sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
    sudo sed -i 's/^#*PermitRootLogin.*/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config
    sudo systemctl restart ssh

    # Check time synchronization status
    timedatectl status
    sudo systemctl status chrony

Bootstrap Ceph Cluster
~~~~~~~~~~~~~~~~~~~~~~~~

- Initialize the Ceph cluster on the first node (ceph-node01).

.. code-block:: bash
    # Update package list and install cephadm
    sudo apt update
    sudo apt install -y cephadm

    # Bootstrap the Ceph cluster
    sudo cephadm bootstrap \
        --mon-ip 192.168.198.101 \
        --cluster-network 192.168.198.0/24 \
        --initial-dashboard-user admin \
        --initial-dashboard-password admin123 \
        --allow-fqdn-hostname

    # Install ceph-common utilities
    sudo apt update && sudo apt install -y ceph-common

    # Set Grafana API URL for the dashboard
    ceph dashboard set-grafana-api-url http://192.168.198.201:3000

- Verify the bootstrap was successful:

.. code-block:: bash
    # Check cluster status
    ceph -s
    ceph status
    ceph orch host ls


Add Nodes to Cluster
+++++++++++++++++++++

Add the remaining nodes to the Ceph cluster for distributed storage.

From `ceph-node01`:

.. code-block:: bash
    # Copy Ceph public key to other nodes for cluster management
    sudo ssh-copy-id -f -i /etc/ceph/ceph.pub root@ceph-node02
    sudo ssh-copy-id -f -i /etc/ceph/ceph.pub root@ceph-node03

    # Test SSH connections
    ssh root@ceph-node02 hostname
    ssh root@ceph-node03 hostname


    # Add nodes to the cluster
    sudo ceph orch host add ceph-node02 192.168.198.102
    sudo ceph orch host add ceph-node03 192.168.198.103  

    # Verify all hosts are added
    ceph orch host ls
    ceph -s

Disable initial security warnings:


.. code-block:: bash
    sudo ceph config set global mon_warn_on_insecure_global_id_reclaim false
    sudo ceph config set global mon_warn_on_insecure_global_id_reclaim_allowed false


Deploy Ceph Services
+++++++++++++++++++++

Deploy the core Ceph services across the cluster.


.. code-block:: bash
    # Deploy Monitor (MON) daemons - 3 monitors for quorum
    sudo ceph orch apply mon --placement "ceph-node01,ceph-node02,ceph-node03"
    sudo ceph mon stat

    # Deploy Manager (MGR) daemons for cluster management
    sudo ceph orch apply mgr --placement "ceph-node01,ceph-node02,ceph-node03"
    sudo ceph mgr module ls

    # Deploy OSDs (Object Storage Daemons) on all available devices
    sudo ceph orch device ls
    sudo ceph orch apply osd --all-available-devices
    sudo ceph osd tree



Openstack AIO node Setup
-------------------------
This section guides you through the setup of an **All-in-One (AIO)** OpenStack node using Kolla-Ansible.

Configure Network
~~~~~~~~~~~~~~~~~~~

We will disable the default network management by cloud-init and set a static IP configuration via Netplan.
**1. Disable cloud-init network configuration and clean up files:**
.. code-block:: bash
    echo "network: {config: disabled}" | sudo tee /etc/cloud/cloud.cfg.d/99-disable-network-config.cfg

    # Remove cloud-init generated files
    sudo rm -f /etc/netplan/50-cloud-init.yaml
    sudo rm -f /etc/netplan/90-installer-network.yaml
    sudo cloud-init clean --logs

**2. Configure network interfaces using Netplan (Adjust interface names as needed):**
.. code-block:: bash
    sudo cat << EOF | sudo tee /etc/netplan/01-netcfg.yaml
    network:
      version: 2
      renderer: networkd
      ethernets:
        ens33:
          addresses:
            - 192.168.198.110/24 # Internal/API network IP
          routes:
            - to: 0.0.0.0/0
              via: 192.168.198.2
          nameservers:
            addresses:
              - 8.8.8.8
          dhcp4: false
    
        ens34:
          dhcp4: false # This interface will be used for Neutron external network
          optional: true
    EOF

    sudo chmod 600 /etc/netplan/01-netcfg.yaml
    sudo chown root:root /etc/netplan/01-netcfg.yaml

**3. Generate and apply the network configuration:**
.. code-block:: bash
    sudo netplan generate
    sudo netplan apply


Install Prerequisites and Docker
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Install essential packages, including Docker, Git, and Python development libraries required for Kolla-Ansible deployment.
**1. Update packages and install initial dependencies:**
.. code-block:: bash
    sudo apt update && sudo apt -y upgrade
    sudo apt install apt-transport-https ca-certificates curl software-properties-common

**2. Install Docker components:**
.. code-block:: bash

    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg
    echo "deb [arch=amd64 signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
    sudo apt update
    sudo apt install docker-ce docker-ce-cli containerd.io
    sudo systemctl start docker
    sudo systemctl enable docker

**3. Install additional required tools and libraries:**

.. code-block:: bash

    sudo apt-get install -y git python3-dev libffi-dev gcc libssl-dev pkg-config libdbus-1-dev build-essential cmake libglib2.0-dev mariadb-server
    sudo apt install -y python3-venv

Setup Kolla-Ansible Environment
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Prepare the working directory and install Kolla-Ansible within a Python virtual environment (venv).

**1. Create the working directory and Python virtual environment:**

.. code-block:: bash

    mkdir -p ~/openstack
    cd ~/openstack
    python3 -m venv .
    source bin/activate

**2. Upgrade pip and install core dependencies:**

.. code-block:: bash

    pip install --upgrade pip
    pip install setuptools docker dbus-python

**3. Configure passwordless sudo for the current user:**

.. note:: Replace ``(username)`` with your actual username. This is necessary for Kolla-Ansible operations.

.. code-block:: bash

    sudo EDITOR=nano visudo
    # Add the following line at the end of the file:
    # (username) ALL=(ALL) NOPASSWD:ALL

**4. Install Ansible and clone Kolla-Ansible repository:**

.. code-block:: bash

    pip install "ansible-core>=2.15,<2.16"
    cd ~/openstack
    git clone https://opendev.org/openstack/kolla-ansible
    cd kolla-ansible
    git branch -a
    git checkout stable/2024.2
    pip install .

**5. Verify Kolla-Ansible installation path:**

.. code-block:: bash

    which kolla-ansible

Configure Kolla-Ansible
~~~~~~~~~~~~~~~~~~~~~~~~~

Set up the configuration files and inventory necessary for the AIO deployment.

**1. Set up the Kolla configuration directory and permissions:**

.. code-block:: bash

    sudo mkdir -p /etc/kolla
    sudo chown $USER:$USER /etc/kolla

**2. Copy example configuration files and the AIO inventory file:**

.. code-block:: bash

    cp -r ~/openstack/share/kolla-ansible/etc_examples/kolla/* /etc/kolla
    cp ~/openstack/share/kolla-ansible/ansible/inventory/all-in-one .

**3. Generate secrets for OpenStack services:**

.. code-block:: bash

    cd ~/openstack
    kolla-genpwd

**4. Edit the global configuration file (``/etc/kolla/globals.yml``):**

.. code-block:: bash

    sudo nano /etc/kolla/globals.yml

    # Ensure the following settings are configured:
    # 
    # kolla_base_distro: "ubuntu"
    # openstack_release: "2024.2"
    # 
    # kolla_internal_vip_address: "192.168.198.149" # Virtual IP for API access
    # 
    # network_interface: "ens33" # Interface for OpenStack API/management network
    # neutron_external_interface: "ens34" # Interface for Neutron public network
    # 
    # nova_compute_virt_type: "qemu"
    # 
    # enable_horizon: "yes"


Deploy OpenStack
~~~~~~~~~~~~~~~~~~

Execute the deployment steps using Kolla-Ansible. 

**1. Install Ansible dependencies for Kolla:**

.. code-block:: bash

    cd ~/openstack
    kolla-ansible install-deps

**2. Bootstrap, check prerequisites, and deploy OpenStack:**

.. code-block:: bash

    kolla-ansible bootstrap-servers -i ./all-in-one
    kolla-ansible prechecks -i ./all-in-one
    kolla-ansible deploy -i ./all-in-one

**3. Run post-deployment tasks:**

.. code-block:: bash

    kolla-ansible post-deploy -i ./all-in-one


Final Steps and Verification
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Install the OpenStack client and perform initial configuration tasks.

**1. Install OpenStack command-line client:**

.. code-block:: bash

    pip install python-openstackclient -c https://releases.openstack.org/constraints/upper/2025.1

**2. Load the OpenStack environment variables:**

.. code-block:: bash

    cd /etc/kolla
    ls
    source /etc/kolla/admin-openrc.sh

**3. Run the initial configuration script:**

.. code-block:: bash

    cd ~/openstack/kolla-ansible/tools
    ./init-runonce


Monitor Node Setup (Prometheus & Grafana)
------------------------------------------

This node serves as the dedicated monitoring server, hosting Prometheus and Grafana to collect metrics from the Ceph and OpenStack clusters.

Configure Hostname and Host Resolution
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

First, set the unique hostname for the monitoring server and update the ``/etc/hosts`` file to ensure name resolution across the cluster.

**1. Update the /etc/hosts file with cluster nodes:**

.. code-block:: bash

    cat << EOF | sudo tee /etc/hosts
    127.0.0.1   localhost
    192.168.198.101 ceph-node01
    192.168.198.102 ceph-node02
    192.168.198.103 ceph-node03

    192.168.198.110 openstack-aio
    192.168.198.111 monitor-node
    192.168.198.112 loki-server
    EOF

**2. Set the node's hostname:**

.. code-block:: bash

    sudo hostnamectl set-hostname monitor-node

Configure Network
~~~~~~~~~~~~~~~~~~~

Disable cloud-init network management and configure a static IP address for the monitor node.

**1. Disable cloud-init network configuration and clean up files:**

.. code-block:: bash

    # Disable cloud-init network configuration
    echo "network: {config: disabled}" | sudo tee /etc/cloud/cloud.cfg.d/99-disable-network-config.cfg

    # Remove cloud-init generated files
    sudo rm -f /etc/netplan/50-cloud-init.yaml
    sudo rm -f /etc/netplan/90-installer-network.yaml
    sudo cloud-init clean --logs

**2. Configure static IP via Netplan (using IP 192.168.198.111):**

.. code-block:: bash

    cat << EOF | sudo tee /etc/netplan/01-netcfg.yaml
    network:
        version: 2
        renderer: networkd
        ethernets:
        ens33:
            addresses:
            - 192.168.198.111/24  # [REPLACE WITH YOUR NODE'S IP]
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

**3. Apply the network configuration:**

.. code-block:: bash

    sudo chmod 600 /etc/netplan/01-netcfg.yaml
    sudo netplan apply

Install Dependencies and Docker
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Install necessary packages and set up Docker, which may be used for containerized monitoring components in the future.

**1. Update packages and install basic utilities:**

.. code-block:: bash

    sudo apt update && sudo apt upgrade -y
    sudo apt install -y wget curl gnupg lsb-release tar

**2. Install Docker components:**

.. code-block:: bash

    sudo mkdir -p /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

    sudo apt update && sudo apt install -y docker-ce docker-ce-cli containerd.io
    sudo systemctl enable --now docker

Install and Configure Prometheus
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Download, set up, and configure Prometheus to scrape metrics from the Ceph and OpenStack components.

**1. Download, extract, and copy Prometheus binaries:**

.. code-block:: bash

    cd /tmp
    wget https://github.com/prometheus/prometheus/releases/download/v3.5.0/prometheus-3.5.0.linux-amd64.tar.gz
    tar xvfz prometheus-*.tar.gz
    cd prometheus-*
    sudo mkdir -p /opt/prometheus /etc/prometheus
    sudo cp prometheus promtool /opt/prometheus/
    sudo cp -r consoles console_libraries /opt/prometheus/
    sudo chown -R root:root /opt/prometheus/
    sudo ln -s /opt/prometheus/prometheus /usr/local/bin/
    sudo ln -s /opt/prometheus/promtool /usr/local/bin/

**2. Create Prometheus user and set permissions:**

.. code-block:: bash

    sudo useradd --no-create-home --shell /bin/false prometheus
    sudo chown prometheus:prometheus /opt/prometheus /etc/prometheus

**3. Create the Prometheus configuration file (``/etc/prometheus/prometheus.yml``):**

.. note:: This configuration is set up to scrape Prometheus itself, OpenStack AIO's Node Exporter, OpenStack Exporter, and Ceph MGR's Prometheus module.

.. code-block:: yaml

    global:
      scrape_interval: 15s
      external_labels:
        cluster: 'openstack-ceph'

    scrape_configs:
      # Scrape Prometheus self
      - job_name: 'prometheus'
        static_configs:
          - targets: ['localhost:9090']

      # Scrape Node Exporter for OpenStack AIO
      - job_name: 'openstack-node'
        static_configs:
          - targets: ['192.168.198.110:9100']

      # Scrape OpenStack Exporter
      - job_name: 'openstack-exporter'
        static_configs:
          - targets: ['192.168.198.110:9180']

      # Scrape Ceph (MGR Prometheus module required on Ceph nodes)
      - job_name: 'ceph'
        honor_labels: true
        metrics_path: '/'
        static_configs:
          - targets:
            - '192.168.198.101:9283'  # ceph-node01
            - '192.168.198.102:9283'  # ceph-node02
            - '192.168.198.103:9283'  # ceph-node03


**4. Create the systemd service file (``/etc/systemd/system/prometheus.service``):**

.. code-block:: service

    [Unit]
    Description=Prometheus Server
    Wants=network-online.target
    After=network-online.target

    [Service]
    User=prometheus
    Group=prometheus
    Type=simple
    ExecStart=/opt/prometheus/prometheus \
        --config.file=/etc/prometheus/prometheus.yml \
        --storage.tsdb.path=/opt/prometheus/data \
        --web.console.templates=/opt/prometheus/consoles \
        --web.console.libraries=/opt/prometheus/console_libraries
    Restart=always

    [Install]
    WantedBy=multi-user.target

**5. Start and enable the Prometheus service:**

.. code-block:: bash

    sudo systemctl daemon-reload
    sudo systemctl enable prometheus
    sudo systemctl start prometheus
    sudo systemctl status prometheus

**6. Verification:**

Access http://192.168.198.111:9090/targets and ensure all targets are listed as **UP**. Open firewall port 9090 if needed (``sudo ufw allow 9090``).


Install and Configure Grafana
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Install Grafana for data visualization and integrate it with the Prometheus data source.

**1. Add Grafana repository and install:**

.. code-block:: bash

    sudo apt-get install -y apt-transport-https software-properties-common wget
    sudo mkdir -p /etc/apt/keyrings/
    wget -q -O - https://apt.grafana.com/gpg.key | gpg --dearmor | sudo tee /etc/apt/keyrings/grafana.gpg > /dev/null
    echo "deb [signed-by=/etc/apt/keyrings/grafana.gpg] https://apt.grafana.com stable main" | sudo tee /etc/apt/sources.list.d/grafana.list
    sudo apt-get update
    sudo apt-get install grafana -y

**2. Start and enable the Grafana service:**

.. code-block:: bash

    sudo systemctl daemon-reload
    sudo systemctl enable grafana-server
    sudo systemctl start grafana-server
    sudo systemctl status grafana-server

**3. Verification:**

Access http://192.168.198.111:3000 (default user: ``admin``, pass: ``admin``). Open firewall port 3000 if needed (``sudo ufw allow 3000``).

**4. Configure Grafana Data Source:**

* Log into Grafana.
* Go to **Configuration** > **Data Sources** > **Add data source** > **Prometheus**.
* Set the URL to: ``http://localhost:9090`` (since Prometheus is on the same node).
* **Save & Test**. The connection must be successful.

**5. Import Dashboards:**

Import recommended dashboards for Ceph and OpenStack visualization. 

* **Ceph:** Search for "Ceph Dashboard" (e.g., ID 12644) on grafana.com/dashboards. Import and select the Prometheus data source.
* **OpenStack:** Search for relevant OpenStack Exporter dashboards (e.g., ID 3662) on grafana.com/dashboards. Import and select the Prometheus data source.

**Final Check:**

.. code-block:: bash

    # Confirm Prometheus API status
    curl http://192.168.198.111:9090/api/v1/status


Loki Server Node Setup
-----------------------

This node is dedicated to running **Loki**, the logging system designed for storing and querying logs efficiently, especially when paired with Grafana. 

Configure Hostname and Host Resolution
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Set the unique hostname for the Loki server and ensure all nodes in the infrastructure can resolve it via ``/etc/hosts``.

**1. Update the /etc/hosts file with cluster nodes:**

.. code-block:: bash

    cat << EOF | sudo tee /etc/hosts
    127.0.0.1   localhost
    192.168.198.101 ceph-node1
    192.168.198.102 ceph-node2
    192.168.198.103 ceph-node3

    192.168.198.110 openstack
    192.168.198.111 monitor-node
    192.168.198.112 loki-server

    EOF

Configure Network
~~~~~~~~~~~~~~~~~~~

Disable cloud-init network management and configure a static IP address for the Loki server using Netplan.

**1. Disable cloud-init and clean up files:**

.. code-block:: bash

    echo "network: {config: disabled}" | sudo tee /etc/cloud/cloud.cfg.d/99-disable-network-config.cfg

    # Remove cloud-init generated files
    sudo rm -f /etc/netplan/50-cloud-init.yaml
    sudo rm -f /etc/netplan/90-installer-network.yaml
    sudo cloud-init clean --logs

**2. Configure static IP via Netplan (IP 192.168.198.112):**

.. code-block:: bash

    cat << EOF | sudo tee /etc/netplan/01-netcfg.yaml
    network:
      version: 2
      renderer: networkd
      ethernets:
        ens33:
          addresses:
            - 192.168.198.112/24
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

**3. Apply the network configuration:**

.. code-block:: bash

    sudo chmod 600 /etc/netplan/01-netcfg.yaml
    sudo netplan apply

Install Dependencies and Docker
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Install standard utilities, Python tools, and Docker to ensure system readiness.

**1. Update packages and install core dependencies:**

.. code-block:: bash

    sudo apt update && sudo apt upgrade -y
    sudo apt install -y wget unzip
    sudo apt install -y python3 python3-pip podman vim htop lvm2 net-tools chrony curl openssh-server

**2. Install Docker components:**

.. code-block:: bash

    # Install Docker prerequisites
    sudo apt install -y ca-certificates curl gnupg lsb-release

    # Add Docker repository key
    sudo mkdir -p /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg

    # Add Docker repository
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

    # Install Docker
    sudo apt update && sudo apt install -y docker-ce docker-ce-cli containerd.io

**3. Enable and start core services:**

.. code-block:: bash

    sudo systemctl enable --now docker chrony


Configure Firewall (UFW)
~~~~~~~~~~~~~~~~~~~~~~~~

Configure the Uncomplicated Firewall (UFW) to allow necessary traffic, especially SSH and the Loki communication ports (HTTP 3100, gRPC 9096) from the cluster network.

**1. Install, reset, and configure UFW defaults:**

.. code-block:: bash

    sudo apt install -y ufw
    sudo ufw --force reset
    sudo ufw default deny incoming
    sudo ufw default allow outgoing

**2. Allow required ports and cluster traffic:**

.. code-block:: bash

    sudo ufw allow 22/tcp comment 'SSH Access'
    sudo ufw allow from 192.168.198.0/24 to any port 3100 proto tcp comment 'Loki HTTP Port'
    sudo ufw allow from 192.168.198.0/24 to any port 9096 proto tcp comment 'Loki gRPC Port'
    sudo ufw allow from 192.168.198.0/24 comment 'Cluster Network'

**3. Enable and verify UFW:**

.. code-block:: bash

    sudo ufw enable
    sudo ufw status verbose


Install Loki Binary
~~~~~~~~~~~~~~~~~~~~

Download the Loki binary, create the dedicated user, and set up the necessary directories for log storage.

**1. Create user and directories:**

.. code-block:: bash

    sudo useradd --no-create-home --shell /bin/false loki
    sudo mkdir -p /opt/loki/data
    sudo mkdir -p /etc/loki

**2. Download and install Loki binary:**

.. code-block:: bash

    cd /tmp
    wget https://github.com/grafana/loki/releases/download/v3.5.9/loki-linux-amd64.zip
    unzip loki-linux-amd64.zip
    sudo mv loki-linux-amd64 /usr/local/bin/loki
    sudo chmod +x /usr/local/bin/loki


Configure Loki (loki.yml)
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Create the configuration file defining Loki's server settings, storage paths, retention policies, and schema.

**1. Create the configuration file (``/etc/loki/loki.yml``):**

.. code-block:: yaml

    cat << EOF | sudo tee /etc/loki/loki.yml
    auth_enabled: false

    server:
      http_listen_port: 3100
      grpc_listen_port: 9096
      http_listen_address: 0.0.0.0
      grpc_listen_address: 0.0.0.0

    common:
      instance_addr: 192.168.198.112
      path_prefix: /opt/loki/data
      storage:
        filesystem:
          chunks_directory: /opt/loki/data/chunks
          rules_directory: /opt/loki/data/rules
      replication_factor: 1
      ring:
        kvstore:
          store: inmemory

    schema_config:
      configs:
        - from: 2025-11-11
          store: tsdb
          object_store: filesystem
          schema: v13
          index:
            prefix: index_
            period: 24h

    # Retention Configuration
    compactor:
      working_directory: /opt/loki/data/compactor
      retention_enabled: true
      delete_request_store: filesystem

    limits_config:
      retention_period: 168h
      reject_old_samples: true
      reject_old_samples_max_age: 168h

    analytics:
      reporting_enabled: false
    EOF

**2. Set ownership for Loki data directory:**

.. code-block:: bash

    sudo chown -R loki:loki /opt/loki


Create and Run Loki Service
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Define the systemd service unit to manage the Loki process and enable it for automatic startup.

**1. Create the systemd service file (``/etc/systemd/system/loki.service``):**

.. code-block:: service

    cat << EOF | sudo tee /etc/systemd/system/loki.service
    [Unit]
    Description=Loki Service
    After=network.target

    [Service]
    Type=simple
    User=loki
    ExecStart=/usr/local/bin/loki -config.file=/etc/loki/loki.yml
    Restart=on-failure

    [Install]
    WantedBy=multi-user.target
    EOF

**2. Reload systemd, enable, and start Loki:**

.. code-block:: bash

    sudo systemctl daemon-reload
    sudo systemctl enable --now loki
    sudo systemctl status loki