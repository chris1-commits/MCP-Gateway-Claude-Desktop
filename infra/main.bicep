// Opulent Horizons MCP Gateway — Azure Container Apps Infrastructure
//
// Deploys:
//   - Container Apps Environment
//   - Lead Ingest MCP Server (port 8001)
//   - Zoho CRM Sync MCP Server (port 8002)
//   - Azure Container Registry
//   - Azure Database for PostgreSQL Flexible Server
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

@secure()
@description('API key for authenticating MCP HTTP requests (Bearer token)')
param mcpApiKey string = ''

@secure()
@description('PostgreSQL administrator password')
param pgAdminPassword string

@description('PostgreSQL administrator username')
param pgAdminUser string = 'opulent'

@description('PostgreSQL database name')
param pgDatabaseName string = 'opulent_mcp'

// ---------------------------------------------------------------------------
// Variables
// ---------------------------------------------------------------------------

var prefix = 'opulent-mcp-${environmentName}'
var acrName = replace('acr${prefix}', '-', '')
var pgServerName = '${prefix}-pg'

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
// PostgreSQL Flexible Server
// ---------------------------------------------------------------------------

resource pgServer 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' = {
  name: pgServerName
  location: location
  sku: {
    name: 'Standard_B1ms'
    tier: 'Burstable'
  }
  properties: {
    version: '16'
    administratorLogin: pgAdminUser
    administratorLoginPassword: pgAdminPassword
    storage: {
      storageSizeGB: 32
    }
    backup: {
      backupRetentionDays: 7
      geoRedundantBackup: 'Disabled'
    }
    highAvailability: {
      mode: 'Disabled'
    }
  }
}

// Allow Azure services (Container Apps) to reach the database
resource pgFirewallAzure 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2024-08-01' = {
  parent: pgServer
  name: 'AllowAzureServices'
  properties: {
    startIpAddress: '0.0.0.0'
    endIpAddress: '0.0.0.0'
  }
}

// Create the application database
resource pgDatabase 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2024-08-01' = {
  parent: pgServer
  name: pgDatabaseName
  properties: {
    charset: 'UTF8'
    collation: 'en_US.utf8'
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
  dependsOn: [pgDatabase]
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
        {
          name: 'mcp-api-key'
          value: mcpApiKey
        }
        {
          name: 'pg-password'
          value: pgAdminPassword
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
            { name: 'MCP_API_KEY', secretRef: 'mcp-api-key' }
            { name: 'PGHOST', value: '${pgServer.name}.postgres.database.azure.com' }
            { name: 'PGPORT', value: '5432' }
            { name: 'PGUSER', value: pgAdminUser }
            { name: 'PGPASSWORD', secretRef: 'pg-password' }
            { name: 'PGDATABASE', value: pgDatabaseName }
            { name: 'PGSSLMODE', value: 'require' }
            { name: 'WORKFLOW_WEBHOOK_URL', value: '' }
            { name: 'TWILIO_AUTH_TOKEN', value: '' }
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
  dependsOn: [pgDatabase]
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
        {
          name: 'mcp-api-key'
          value: mcpApiKey
        }
        {
          name: 'pg-password'
          value: pgAdminPassword
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
            { name: 'MCP_API_KEY', secretRef: 'mcp-api-key' }
            { name: 'ZOHO_API_BASE', value: zohoApiBase }
            { name: 'ZOHO_TOKEN_URL', value: zohoTokenUrl }
            { name: 'ZOHO_CLIENT_ID', secretRef: 'zoho-client-id' }
            { name: 'ZOHO_CLIENT_SECRET', secretRef: 'zoho-client-secret' }
            { name: 'ZOHO_REFRESH_TOKEN', secretRef: 'zoho-refresh-token' }
            { name: 'ZOHO_ACCESS_TOKEN', value: '' }
            { name: 'PROPERTY_DB_HOST', value: '${pgServer.name}.postgres.database.azure.com' }
            { name: 'PROPERTY_DB_PORT', value: '5432' }
            { name: 'PROPERTY_DB_USER', value: pgAdminUser }
            { name: 'PROPERTY_DB_PASSWORD', secretRef: 'pg-password' }
            { name: 'PROPERTY_DB_NAME', value: pgDatabaseName }
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
output pgFqdn string = '${pgServer.name}.postgres.database.azure.com'
