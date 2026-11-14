# Pantheon Systems (formerly Ares VPS)

Free for noncommercial use under the PolyForm Noncommercial License 1.0.0. For commercial licensing, contact <jakub.niedzwiedz98@gmail.com>

## Goals

Pantheon is a learning-focused infrastructure project for building a reproducible and expandable network of VPS servers and NAS devices. The goal is to configure the complete environment on one or more machines through a bootstrap script.

### Current Focus

Learning server automation and web hosting by setting up a VPS for my website, while keeping the project as expandable as possible.

### AI Usage

AI usage should be kept to a minimum and limited primarily to documentation and learning support. All code should be written by me, by hand.

Track new AI contributions with [Git AI](https://usegitai.com/), which records line-level attribution in Git Notes instead of source comments. Install Git AI and run `git ai install-hooks`, then restart your coding agent to activate its integration. Use `git ai status` to inspect working changes and `git ai blame <file>` to inspect committed attribution.

Existing `ai_generated` comments and Markdown tags are legacy AI markers and remain in place; they do not retroactively populate Git AI attribution. Do not add new inline AI markers.

## Parts of the System

### Hermes VPS

The system is currently being built around a single VPS. It is intended to host my website, blog, form relay, Matrix server, and any other required services. Eventually, these services may be separated across multiple dedicated machines.

## Assumptions

- All servers run a preconfigured Ubuntu Server cloud image.
