Observability Document
======================

Project Overview: Goals and Scope
---------------------------------
This project sets up a basic observability solution to collect and centralize logs and metrics from Ceph and OpenStack clusters. The main goal is to provide a single place to monitor these systems, helping to identify issues and understand their performance.

This is a foundational solution. It works for monitoring and troubleshooting in development or staging environments, but will require significant improvements and hardening before it can be considered production-ready.

**Key Objectives:**

- Unified Monitoring: Bring logs and metrics from Ceph and OpenStack into one dashboard.
- Faster Debugging: Reduce troubleshooting time by allowing you to search logs and view related metrics together.
- Performance Insight: Track system health, resource usage, and service latency.


The solution is built around two main data types: **logs** and **metrics**.

1. Centralized Logging

* Collection: Lightweight agents (Promtail) are deployed on each node to collect log files (from `/var/log/ceph`, `/var/log/nova`, etc.).
* Processing & Storage: Logs are sent to a central processing service (Loki), where they are indexed and stored.
* Format: Applications should output structured logs (like JSON) where possible, but the system can also handle plain text logs.

2. Metrics Collection

* Method: Uses a pull-based model with Prometheus.
* Standardization: Services expose metrics in the Prometheus format on an HTTP endpoint (like `/metrics`).
* Scraping: Prometheus servers periodically scrape (collect) metrics from these endpoints and store them as time-series data.
* Key Metric Sources:
   * Node Exporter: For basic host metrics (CPU, memory, disk space).
   * Ceph Exporter & OpenStack Exporters: For cluster-specific health and performance metrics.

Document Structure 
~~~~~~~~~~~~~~~~~~

The following table of contents of the projects.

.. toctree::
   :maxdepth: 3
   :caption: Main Concepts
   
   architecture 
   prerequisites
   
.. toctree::
   :maxdepth: 3
   :caption: Project Workflow
   
   deployment/index
   testing/index  


