// Opulent Horizons MCP Gateway — Azure Container Apps Infrastructure
//
// Deploys:
//   - Container Apps Environment
//   - Lead Ingest MCP Server (port 8001)
//   - Zoho CRM Sync MCP Server (port 8002)
//   - Azure Container Registry
//
// Usage:
//   az deployment group create \
//     --resource-group mcp-gw-rg \
//     --template-file infra/main.bicep \
//     --parameters environmentName=dev

@description('Environment name (dev, staging, prod)')
param environmentName string = 'dev'

@description('Azure region for all resources')
param location string = resourceGroup().location

@description('Container image tag')
param imageTag string = 'latest'

// Zoho OAuth2 credentials (passed as secure parameters)
@secure()
@description('Zoho OAuth2 Client ID')
param zohoClientId string = ''

@secure()
@description('Zoho OAuth2 Client Secret')
param zohoClientSecret string = ''

@secure()
@description('Zoho OAuth2 Refresh Token')
param zohoRefreshToken string = ''

@description('Zoho API Base URL')
param zohoApiBase string = 'https://www.zohoapis.com.au/crm/v2'

@description('Zoho Token URL')
param zohoTokenUrl string = 'https://accounts.zoho.com.au/oauth/v2/token'

// ---------------------------------------------------------------------------
// Variables
// ---------------------------------------------------------------------------

var prefix = 'opulent-mcp-${environmentName}'
var acrName = replace('acr${prefix}', '-', '')

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
        {
          name: 'zoho-client-id'
          value: zohoClientId
        }
        {
          name: 'zoho-client-secret'
          value: zohoClientSecret
        }
        {
          name: 'zoho-refresh-token'
          value: zohoRefreshToken
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
            { name: 'ZOHO_API_BASE', value: zohoApiBase }
            { name: 'ZOHO_TOKEN_URL', value: zohoTokenUrl }
            { name: 'ZOHO_CLIENT_ID', secretRef: 'zoho-client-id' }
            { name: 'ZOHO_CLIENT_SECRET', secretRef: 'zoho-client-secret' }
            { name: 'ZOHO_REFRESH_TOKEN', secretRef: 'zoho-refresh-token' }
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
