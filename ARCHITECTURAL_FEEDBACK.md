# Architectural Vision & User Feedback (2026-04-14)

This document captures the distilled user feedback regarding the evolution of the **Track** project. The intent is to provide a clear roadmap for future development while maintaining the flexibility of independent sub-projects.

## 1. Project Organization: The "Umbrella" Model
**Track** was designed from its inception as an "umbrella" project to encompass several distinct sub-projects. Although **Map3D** was implemented first and currently dominates the codebase, the original vision (as documented in `GOALS.md`) intended a unified system for:
- **Net Inventory**: A system for managing and tracking network assets and infrastructure.
- **Map3D**: 3D space mapping and reconstruction tools.
- **Web Control**: Interfaces for direct web-based control of specialized local devices.
- **Ansible Automation**: Using Ansible for automated task execution and system configuration.

### Rationale for the "Umbrella" Shift
Currently, the Map3D application takes over the entire web interface. This was not the long-term intent. Map3D must be treated as a **sub-application** within a larger dashboard. The top-level architecture should allow for independent development of these "kits" while providing a unified "One Web Interface to Rule Them All."

## 2. Infrastructure & Hosting Strategy
### The "Workstation-Off" Case Study
Current development on a home workstation using Cloudflare tunnels has proven fragile (e.g., if the workstation is powered off, the tunnel goes down). To ensure 24/7 availability for field use (e.g., at work or a museum), the system must transition to a dedicated server environment.

### GPU vs. CPU Node Separation
- **Management Server**: Likely a CPU-only head-end server running the web interface and basic database operations.
- **Processing Nodes**: Resource-intensive Map3D tasks—such as feature extraction, model updates, and 3D rendering—require nodes equipped with proper GPUs.

### Shared Storage & Mounting Risks
One proposed solution is to mount a shared drive and run software locally across nodes. 
> [!CAUTION]
> **Architecture Mismatch**: Sharing binaries or environments via mounted drives carries a high risk of "VM clashes" or crashes if nodes use different processor architectures (e.g., ARM vs. x86). This remains an open design consideration.

## 3. Deployment & Publishing Plan
As sub-projects may run as independent Flask applications, we must decide between two primary hosting strategies:
1.  **Uniform Integration (Unite)**: Use a single master Flask app that integrates sub-projects as **Blueprints**. This simplifies session management and common data sharing but couples the codebases.
2.  **Service Proxying (Proxy)**: Run each sub-app as its own standalone service/Flask app and use a **Reverse Proxy** (e.g., Nginx or a master landing app) to route requests (e.g., `/map3d`, `/net-inventory`). This allows for completely independent development and heterogeneous environments (some on GPU nodes, some on CPU nodes).

## 4. Data Integration & "Master Tags"
While sub-projects like Net Inventory maintain specialized databases, they share a common metadata layer:
- **Common Entities**: "Locations" (Root, Sub, Sub-Sub) and "Tags."
- **Master Tag Record**: A global, shared record providing a consistent "pull-down" selection menu (e.g., "I am here", "I am in this room") across all sub-apps.
- **Application Flexibility**: Each sub-app is free to define and edit its own application-specific tags while pulling from the Master Record.

## 5. Federated Frontend & Security
The authentication model must shift from "Log in then select location" to a location-aware flow:
- **Root Landing Page**: A simple entry page asking: "Where do you want to go? (Testing/Home, Museum, Lab)."
- **Per-Location Isolation**: Each location requires its own **distinct password/credentials**. 
    - *User Requirement*: Museum staff should have zero visibility or access to the private "Home/Testing" environment.
- **Mirrored Functionality**: The UI/code may be mirrored across environments for consistency, but the access remains strictly siloed by location-based credentials.
- **Deep Hierarchy**: Continued support for nested location structures (Building > Room > Cabinet).
