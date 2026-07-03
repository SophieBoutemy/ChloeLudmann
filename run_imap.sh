#!/bin/bash
cd /home/ubuntu/automations
source venv/bin/activate
python imap_to_notion_chloe.py >> /home/ubuntu/automations/chloe.log 2>&1
