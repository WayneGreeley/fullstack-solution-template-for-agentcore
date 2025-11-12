#!/usr/bin/env node
import * as cdk from "aws-cdk-lib"
import { GaspMainStack } from "../lib/gasp-main-stack"
import { ConfigManager } from "../lib/utils/config-manager"

// Load configuration using ConfigManager
const configManager = new ConfigManager("config.yaml")

// Initial props consist of configuration parameters
const props = configManager.getProps()

const app = new cdk.App()

// Deploy the new Amplify-based stack that solves the circular dependency
const amplifyStack = new GaspMainStack(app, props.stack_name_base, {
  config: props,
  env: { 
    account: process.env.CDK_DEFAULT_ACCOUNT, 
    region: process.env.CDK_DEFAULT_REGION 
  },
})

app.synth()
