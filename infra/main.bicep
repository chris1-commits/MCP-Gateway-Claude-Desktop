// Opulent Horizons MCP Gateway — Azure Container Apps Infrastructure
//
// Deploys:
//   - Container Apps Environment
//   - Lead Ingest MCP Server (port 8001)
//   - Zoho CRM Sync MCP Server (port 8002)
//   - Azure Container Registry
//   - Key Vault for secrets
//
// Usage:
//   az deployment group create \
//     --resource-group rg-opulent-mcp \
//     --template-file infra/main.bicep \
//     --parameters environmentName=prod

@description('Environment name (dev, staging, prod)')
param environmentName string = 'dev'

@description('Azure region for all resources')
param location string = resourceGroup().location

@description('Container image tag')
param imageTag string = 'latest'

// ---------------------------------------------------------------------------
// Variables
// ---------------------------------------------------------------------------

var prefix = 'opulent-mcp-${environmentName}'
var acrName = replace('acr${prefix}', '-', '')
var kvName = 'kv-${prefix}'

// ---------------------------------------------------------------------------
// Container Registry
// ---------------------------------------------------------------------------

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: acrName
  location: location
  sku: {
    name: 'Basic'
  }
  properties: {
    adminUserEnabled: true
  }
}

// ---------------------------------------------------------------------------
// Key Vault
// ---------------------------------------------------------------------------

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: kvName
  location: location
  properties: {
    sku: {
      family: 'A'
      name: 'standard'
    }
    tenantId: subscription().tenantId
    accessPolicies: []
    enableRbacAuthorization: true
  }
}

// ---------------------------------------------------------------------------
// Container Apps Environment
// ---------------------------------------------------------------------------

resource containerEnv 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: '${prefix}-env'
  location: location
  properties: {
    zoneRedundant: false
  }
}

// ---------------------------------------------------------------------------
// Lead Ingest MCP Server
// ---------------------------------------------------------------------------

resource leadIngest 'Microsoft.App/containerApps@2024-03-01' = {
  name: '${prefix}-lead-ingest'
  location: location
  properties: {
    managedEnvironmentId: containerEnv.id
    configuration: {
      ingress: {
        external: true
        targetPort: 8001
        transport: 'http'
        allowInsecure: false
      }
      registries: [
        {
          server: acr.properties.loginServer
          username: acr.listCredentials().username
          passwordSecretRef: 'acr-password'
        }
      ]
      secrets: [
        {
          name: 'acr-password'
          value: acr.listCredentials().passwords[0].value
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'lead-ingest'
          image: '${acr.properties.loginServer}/opulent-mcp-gateway:${imageTag}'
          resources: {
            cpu: json('0.25')
            memory: '0.5Gi'
          }
          env: [
            { name: 'MCP_SERVER', value: 'lead_ingest' }
            { name: 'MCP_PORT', value: '8001' }
            { name: 'PGHOST', value: '' }
            { name: 'PGDATABASE', value: '' }
            { name: 'WORKFLOW_WEBHOOK_URL', value: '' }
            { name: 'CLOUDTALK_WEBHOOK_SECRET', value: '' }
            { name: 'NOTION_WEBHOOK_SECRET', value: '' }
          ]
        }
      ]
      scale: {
        minReplicas: 0
        maxReplicas: 3
        rules: [
          {
            name: 'http-scale'
            http: {
              metadata: {
                concurrentRequests: '10'
              }
            }
          }
        ]
      }
    }
  }
}

// ---------------------------------------------------------------------------
// Zoho CRM Sync MCP Server
// ---------------------------------------------------------------------------

resource zohoSync 'Microsoft.App/containerApps@2024-03-01' = {
  name: '${prefix}-zoho-sync'
  location: location
  properties: {
    managedEnvironmentId: containerEnv.id
    configuration: {
      ingress: {
        external: true
        targetPort: 8002
        transport: 'http'
        allowInsecure: false
      }
      registries: [
        {
          server: acr.properties.loginServer
          username: acr.listCredentials().username
          passwordSecretRef: 'acr-password'
        }
      ]
      secrets: [
        {
          name: 'acr-password'
          value: acr.listCredentials().passwords[0].value
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'zoho-sync'
          image: '${acr.properties.loginServer}/opulent-mcp-gateway:${imageTag}'
          resources: {
            cpu: json('0.25')
            memory: '0.5Gi'
          }
          env: [
            { name: 'MCP_SERVER', value: 'zoho_crm_sync' }
            { name: 'MCP_PORT', value: '8002' }
            { name: 'ZOHO_API_BASE', value: 'https://www.zohoapis.com/crm/v2' }
            { name: 'ZOHO_ACCESS_TOKEN', value: '' }
            { name: 'PROPERTY_DB_HOST', value: '' }
            { name: 'PROPERTY_DB_PORT', value: '5432' }
            { name: 'PROPERTY_DB_USER', value: '' }
            { name: 'PROPERTY_DB_PASSWORD', value: '' }
            { name: 'PROPERTY_DB_NAME', value: 'property_db' }
          ]
        }
      ]
      scale: {
        minReplicas: 0
        maxReplicas: 3
        rules: [
          {
            name: 'http-scale'
            http: {
              metadata: {
                concurrentRequests: '10'
              }
            }
          }
        ]
      }
    }
  }
}

// ---------------------------------------------------------------------------
// Outputs
// ---------------------------------------------------------------------------

output leadIngestUrl string = 'https://${leadIngest.properties.configuration.ingress.fqdn}'
output zohoSyncUrl string = 'https://${zohoSync.properties.configuration.ingress.fqdn}'
output acrLoginServer string = acr.properties.loginServer
output keyVaultName string = keyVault.name
