#!/bin/bash

# Check if AWS CLI is installed
if ! command -v aws &> /dev/null; then
    echo "AWS CLI not found. Please install it first."
    exit 1
fi

# Get all EC2 instances
echo "Fetching EC2 instances..."
instances=$(aws ec2 describe-instances \
    --query 'Reservations[*].Instances[*].[InstanceId,Tags[?Key==`Name`].Value|[0],State.Name,PrivateIpAddress,PublicIpAddress,InstanceType]' \
    --output text)

if [[ -z "$instances" ]]; then
    echo "No EC2 instances found."
    exit 0
fi

# Display instances in table format
printf "%-20s %-30s %-15s %-15s %-15s %-15s\n" "INSTANCE ID" "NAME" "STATE" "PRIVATE IP" "PUBLIC IP" "TYPE"
printf "%.0s-" {1..120}
echo ""

declare -a stopped_instances=()
declare -a stopped_ids=()

while IFS=$'\t' read -r id name state private_ip public_ip type; do
    printf "%-20s %-30s %-15s %-15s %-15s %-15s\n" "$id" "${name:-N/A}" "$state" "${private_ip:-N/A}" "${public_ip:-N/A}" "$type"
    
    if [[ "$state" == "stopped" ]]; then
        stopped_instances+=("$id - ${name:-N/A}")
        stopped_ids+=("$id")
    fi
done <<< "$instances"

# Offer to start stopped instances
if [[ ${#stopped_instances[@]} -gt 0 ]]; then
    echo ""
    echo "Found ${#stopped_instances[@]} stopped instance(s)."
    read -p "Would you like to start any stopped instances? (y/n): " answer
    
    if [[ "$answer" == "y" ]]; then
        echo ""
        echo "Stopped instances:"
        for i in "${!stopped_instances[@]}"; do
            echo "$((i+1)). ${stopped_instances[$i]}"
        done
        
        read -p "Enter instance number(s) to start (comma-separated, or 'all'): " selection
        
        if [[ "$selection" == "all" ]]; then
            echo "Starting all stopped instances..."
            aws ec2 start-instances --instance-ids "${stopped_ids[@]}"
            echo "Started all instances!"
        else
            IFS=',' read -ra selected <<< "$selection"
            instances_to_start=()
            for num in "${selected[@]}"; do
                num=$(echo "$num" | xargs) # trim whitespace
                if [[ "$num" =~ ^[0-9]+$ ]] && [[ "$num" -ge 1 ]] && [[ "$num" -le ${#stopped_ids[@]} ]]; then
                    instances_to_start+=("${stopped_ids[$((num-1))]}")
                fi
            done
            
            if [[ ${#instances_to_start[@]} -gt 0 ]]; then
                echo "Starting instances: ${instances_to_start[*]}"
                aws ec2 start-instances --instance-ids "${instances_to_start[@]}"
                echo "Started successfully!"
            fi
        fi
    fi
fi