#!/bin/bash
set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Helper functions
log_info() {
    echo -e "${BLUE}ℹ${NC} $1"
}

log_success() {
    echo -e "${GREEN}✓${NC} $1"
}

log_error() {
    echo -e "${RED}✗${NC} $1" >&2
}

# Get stack name from config or environment
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CDK_DIR="$SCRIPT_DIR/../infra-cdk"

# Change to CDK directory
cd "$CDK_DIR"

# Get stack name from config.yaml
STACK_NAME=$(grep "stack_name_base:" config.yaml | awk '{print $2}' | tr -d '"' || echo "")

if [ -z "$STACK_NAME" ]; then
    log_error "Could not determine stack name from config.yaml"
    exit 1
fi

log_info "Deploying CDK stack: $STACK_NAME"

# Run CDK deploy
if cdk deploy --require-approval never "$@"; then
    log_success "🎉 CDK deployment completed successfully!"
    echo
    log_info "Next steps:"
    log_info "  1. Deploy frontend: ./scripts/deploy-frontend.sh"
    log_info "     (This will generate aws-exports.json and deploy the frontend)"
else
    log_error "CDK deployment failed"
    exit 1
fi