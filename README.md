# Pantheon Systems

Free for noncommercial use under the PolyForm Noncommercial License 1.0.0. For commercial licensing, contact <jakub.niedzwiedz98@gmail.com>

## Goals

Pantheon is a learning-focused infrastructure project for building a reproducible and expandable network of VPS servers and NAS devices. The goal is to configure the complete environment on one or more machines through a bootstrap script.

### Current Focus

Configure Hermes for NetBird-only administration and private HTTPS proxying, then host the public BearWorks website and a few small rootless Podman services. Add separate Ansible-managed hosts as the private network grows.

### AI Usage

AI usage should be kept to a minimum and limited primarily to documentation and learning support. All code should be written by me, by hand.

Track new AI contributions with [Git AI](https://usegitai.com/), which records line-level attribution in Git Notes instead of source comments. Install Git AI and run `git ai install-hooks`, then restart your coding agent to activate its integration. Use `git ai status` to inspect working changes and `git ai blame <file>` to inspect committed attribution.

Existing `ai_generated` comments and Markdown tags are legacy AI markers and remain in place; they do not retroactively populate Git AI attribution. Do not add new inline AI markers.

## Parts of the System

### Hermes VPS

Hermes is the first VPS: a private NetBird-accessible reverse proxy, public website host, and potential host for small private services. Additional hosts can run backends without changing their client-facing URLs.

## Assumptions

- All servers run a preconfigured Ubuntu Server cloud image.
