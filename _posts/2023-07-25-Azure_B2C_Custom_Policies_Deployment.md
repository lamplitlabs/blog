---
layout: post
title: "Azure B2C Custom Policies Deployment - Azure DevOps"
description: "Deploy Azure AD B2C custom policies from Azure DevOps pipelines with token replacement, including fixes for validation issues."
date: 2023-07-25 09:00:00 -0500
categories: azure devops cloud
tags: AzureAD AzureADB2C AzureEntra AzureDevOps
author: manishtiwari25
redirect_from:
  - /blogPost/a474c427-52d8-4f7d-9f65-02822fced323/azure-b2c-custom-policies-deployment-azure-devops
  - /blogPost/a474c427-52d8-4f7d-9f65-02822fced323
  - /automate-azure-b2c-custom-policies-deployment-c6421f1baeb3?source=user_profile---------9----------------------------
  - /automate-azure-b2c-custom-policies-deployment-c6421f1baeb3?source=author_recirc-----7148ce60b54b----2----------------------------
  - /share?text=Azure B2C Custom Policies Deployment - Azure DevOps - Lamplit Labs https://blogs.lamplitlabs.com/posts/Azure_B2C_Custom_Policies_Deployment/
  - /automate-azure-b2c-custom-policies-deployment-c6421f1baeb3?source=author_recirc-----7148ce60b54b----2----------------------------
image:
  path: /assets/img/headers/azure-b2c-azure-devops.webp
  alt: "Diagram of Azure AD B2C custom policy deployment pipeline in Azure DevOps"
---

#### Update 08.08.2023

After testing for a while, I found a few issues for example validation failed if we add more tokens to replace.
so for fixing this, we need to tweak a few things in the policy.

{% include article-ads.html %}

- Add new folder ´templates´ inside pipelines
- Add a new YML file, azure-b2c-jobs.yml, and add following

```yaml
parameters:
  - name: PoliciesFolderPath
    type: string
    default: false
  - name: KeysToReplace
    type: string
    default: false
  - name: VmImage
    default: "ubuntu-latest"

jobs:
  - job: ValidateAndDeploy
    pool:
      vmImage: ${{ parameters.VmImage }}
    steps:
      - checkout: self
      - task: PowerShell@2
        displayName: Replace Tokens
        inputs:
          filePath: "pipelines/scripts/ReplaceToken.ps1"
          arguments: -folderPath ${{ parameters.PoliciesFolderPath }}  -keysToReplace ${{ parameters.KeysToReplace }}
          pwsh: true

      - task: PowerShell@2
        displayName: Validate policies
        inputs:
          filePath: "pipelines/scripts/ValidateXml.ps1"
          arguments: ${{ parameters.PoliciesFolderPath }}
          pwsh: true

      - task: PowerShell@2
        displayName: Deploy policies
        inputs:
          filePath: "pipelines/scripts/Deploy.ps1"
          arguments: $(ClientId) $(ClientSecret) $(TenantId) ${{ parameters.PoliciesFolderPath }}
          pwsh: true
```

{% include article-ads.html %}

- Update the azure-pipeline.yml file

```yaml
trigger: none

variables:
  - group: GraphApiCreds
stages:
  - stage: Release_QA
    displayName: Release QA
    variables:
      - group: QAPolicy
    jobs:
      - template: templates/azure-b2c-jobs.yml
        parameters:
          PoliciesFolderPath: "Policies"
          KeysToReplace: "TENANTNAME,DEPLOYMENTMODE"
  - stage: Release_Production
    displayName: Release Production
    variables:
      - group: ProductionPolicy
    jobs:
      - template: templates/azure-b2c-jobs.yml
        parameters:
          PoliciesFolderPath: "Policies"
          KeysToReplace: "TENANTNAME,DEPLOYMENTMODE"
```

---

{% include article-ads.html %}

After creating a [build and deployment](https://marketplace.visualstudio.com/items?itemName=ManishTiwari-Azureb2c.AzureADB2CBuildTask) task 4 years back, I am back with another trick.

##### Why not use the old [task](https://marketplace.visualstudio.com/items?itemName=ManishTiwari-Azureb2c.AzureADB2CBuildTask)?

Even though it was a fun project, it is very hard to maintain it, so I decided to make it simpler and use Powershell instead.

### Steps

- Please follow [steps from Microsoft](https://learn.microsoft.com/en-us/azure/active-directory-b2c/microsoft-graph-get-started?tabs=app-reg-ga) and note down applicationId, clientSecret and tenantId.
- Create the following folder structure

  ![Folder Structure](/assets/img/posts/folder-structure.png)

{% include article-ads.html %}

- [Deploy.ps1](https://gist.github.com/manishtiwari25/bad34a5544c8c709db31457d9cc94ebb#file-deploy-ps1) contains the script to deploy the files in azure b2c, it takes clientId, clientSectet, tenantId, and folderPath as input.

```php
param(
    [Parameter(Mandatory = $true)]
    [string]$clientID,

    [Parameter(Mandatory = $true)]
    [string]$clientSecret,

    [Parameter(Mandatory = $true)]
    [string]$tenantId,

    [Parameter(Mandatory = $true)]
    [string]$folderPath
)

try {

    $xmlFiles = Get-ChildItem -Path $folderPath -Force | Where-Object -FilterScript {
        $_.Extension -eq ".xml"
    }

    if ($xmlFiles.Count -eq 0) {
        Write-Warning "No XML files found in the specified path $($folderPath)"
        exit
    }

    $body = @{grant_type = "client_credentials"; scope = "https://graph.microsoft.com/.default"; client_id = $ClientID; client_secret = $ClientSecret }

    $response = Invoke-RestMethod -Uri https://login.microsoftonline.com/$TenantId/oauth2/v2.0/token -Method Post -Body $body
    $token = $response.access_token

    $headers = New-Object "System.Collections.Generic.Dictionary[[String],[String]]"
    $headers.Add("Content-Type", 'application/xml')
    $headers.Add("Authorization", 'Bearer ' + $token)

    Foreach ($xmlfile in $xmlFiles) {
        $filePath = $folderPath +'/'+ $xmlfile.Name
        # Check if file exists
        $FileExists = Test-Path -Path $filePath -PathType Leaf

        if ($FileExists) {
            $policycontent = Get-Content $filePath -Encoding UTF8

            # Get the policy name from the XML document
            $match = Select-String -InputObject $policycontent  -Pattern '(?<=\bPolicyId=")[^"]*'

            If ($match.matches.groups.count -ge 1) {
                $PolicyId = $match.matches.groups[0].value

                Write-Host "Uploading the" $PolicyId "policy..."

                $graphuri = 'https://graph.microsoft.com/beta/trustframework/policies/' + $PolicyId + '/$value'
                $content = [System.Text.Encoding]::UTF8.GetBytes($policycontent)
                $response = Invoke-RestMethod -Uri $graphuri -Method Put -Body $content -Headers $headers -ContentType "application/xml; charset=utf-8"

                Write-Host "Policy" $PolicyId "uploaded successfully."
            }
        }
        else {
            $warning = "File " + $filePath + " couldn't be not found."
            Write-Warning -Message $warning
        }
    }
}
catch {
    Write-Host "StatusCode:" $_.Exception.Response.StatusCode.value__

    $_

    $streamReader = [System.IO.StreamReader]::new($_.Exception.Response.GetResponseStream())
    $streamReader.BaseStream.Position = 0
    $streamReader.DiscardBufferedData()
    $errResp = $streamReader.ReadToEnd()
    $streamReader.Close()

    $ErrResp

    exit 1
}

exit 0
```

{% include article-ads.html %}

<br/>

- [ReplaceToken.ps1](https://gist.github.com/manishtiwari25/bad34a5544c8c709db31457d9cc94ebb#file-replacetoken-ps1) contains the script to replace the token within custom policies, it reads the values from libraries.

```php
param(
    [Parameter(Mandatory = $true)]
    [string]$folderPath,

    [Parameter(Mandatory = $true)]
    [string[]]$keysToReplace
)


if ($keysToReplace.Count -eq 0) {
    Write-Warning "no key found to replace"
    exit 1
}
$xmlFiles = Get-ChildItem -Path $folderPath -Force | Where-Object -FilterScript {
    $_.Extension -eq ".xml"
    Write-Host $_
}

if ($xmlFiles.Count -eq 0) {
    Write-Warning "No XML files found in the specified path"
    exit 1
}
Foreach ($file in $xmlFiles) {
    $filePath = $folderPath +'/'+ $file.Name
    # Check if file exists
    $FileExists = Test-Path -Path $filePath -PathType Leaf

    if ($FileExists) {
        $policycontent = Get-Content $filePath -Encoding UTF8
        foreach ($key in $keysToReplace) {
            $policycontent = $policycontent.Replace($key, $(Get-Content env:$key))
        }
        Set-Content $filepath -Value $policycontent -Force
    }
    else {
        $warning = "File " + $filePath + " couldn't be not found."
        Write-Warning -Message $warning
    }
}
```

<br/>

- [ValidateXml.ps1](https://gist.github.com/manishtiwari25/bad34a5544c8c709db31457d9cc94ebb#file-validatexml-ps1) file contains script to validate the XML file against the XSD. it give if there are any error in a line and position.

```php
param (
    [Parameter(Mandatory = $true)]
    [string]$xmlFolderPath
)


$xmlFiles = Get-ChildItem -Path $xmlFolderPath -Force | Where-Object -FilterScript {
    $_.Extension -eq ".xml"
}

if ($xmlFiles.Count -eq 0) {
    Write-Warning "No XML files found in the specified path"
    exit
}


$handler = [System.Xml.Schema.ValidationEventHandler] {
    $copy = $_
    switch ($args.Severity) {
        Error {
            Write-Error "ERROR: line $($copy.Exception.LineNumber)"
            Write-Error "position $($copy.Exception.LinePosition)"
            Write-Error $copy.Message
            throw
        }
        Warning {
            Write-Warning "Warning:: " + $copy.Message
            break
        }
    }
}

try {
    Push-Location (Split-Path $xmlFolderPath)
    $isValid = $true
    $failedFiles = @()
    $xsd = "https://raw.githubusercontent.com/Azure-Samples/active-directory-b2c-custom-policy-starterpack/master/TrustFrameworkPolicy_0.3.0.0.xsd"
    Invoke-WebRequest -Uri $xsd -OutFile "TrustFrameworkPolicy_0.3.0.0.xsd"
    foreach ($xmlfile in $xmlFiles) {
        Write-Host "Validating $($xmlFolderPath + $xmlfile.Name)" -ForegroundColor Cyan

        $settings = new-object System.Xml.XmlReaderSettings
        $null = $settings.Schemas.Add("http://schemas.microsoft.com/online/cpim/schemas/2013/06", "$(Get-Location)/TrustFrameworkPolicy_0.3.0.0.xsd")
        $null = $settings.ValidationType = [System.Xml.ValidationType]::Schema


        $settings.add_ValidationEventHandler($handler)
        $reader = [System.Xml.XmlReader]::Create($xmlfile, $settings)
        $document = new-object System.Xml.XmlDocument
        try {
            $null = $document.Load($reader)
        }
        catch {
            $isValid = $false
            $failedFiles += $xmlfile.Name
        }
        $null = $reader.Close()
    }
    if ($isValid -eq $false) {
        Write-Error "Validation failed for $($failedFiles)"
        exit 1
    }
}
catch {
    throw
}
finally {
    Remove-Item -Path "TrustFrameworkPolicy_0.3.0.0.xsd"
    Pop-Location
}
```

<br/>

{% include feed-ads.html %}

- [azure-pipelines.yml](https://gist.github.com/manishtiwari25/bad34a5544c8c709db31457d9cc94ebb#file-azure-pipelines-yml) code for the pipeline, it is a multi-stage pipeline, with approvals.

```yml
trigger: none

variables:
  - group: GraphApiCreds
stages:
  - stage: Validate
    displayName: Validate
    pool:
      vmImage: ubuntu-latest
    jobs:
      - job: Validate
        steps:
          - task: PowerShell@2
            displayName: Validate policies
            inputs:
              filePath: "pipelines/scripts/ValidateXml.ps1"
              arguments: "Policies"
              pwsh: true
          - publish: $(System.DefaultWorkingDirectory)/Policies
            artifact: drop

  - stage: DeployQA
    displayName: Deploy To QA
    pool:
      vmImage: ubuntu-latest
    variables:
      - group: ProductionPolicy
    dependsOn: [Validate]
    jobs:
      - deployment: DeployQA
        displayName: Deploy to QA
        environment: QA
        strategy:
          runOnce:
            deploy:
              steps:
                - checkout: self
                - download: current
                  artifact: drop
                  patterns: "**/*.xml"
                - task: PowerShell@2
                  displayName: Replace Tokens
                  inputs:
                    filePath: "pipelines/scripts/ReplaceToken.ps1"
                    arguments: -folderPath $(Pipeline.Workspace)/drop  -keysToReplace TENANTNAME
                    pwsh: true
                - task: PowerShell@2
                  displayName: Deploy policies
                  inputs:
                    filePath: "pipelines/scripts/Deploy.ps1"
                    arguments: $(ClientId) $(ClientSecret) $(TenantId) $(Pipeline.Workspace)/drop
                    pwsh: true
```

- In yml file, at the moment I have only one key to replace(-keysToReplace), but you can add multiple keys here and it needs to be comma separated.
- We need to have at least 2 variable groups, one for graph API credentials and the other one for keys and values.
- Create a new variable group (inside the library) GraphApiCreds and add ClientId, ClientSecret, and TenantId
- Create another variable group QAPolicy and add the keys you want to replace with their values. for example TenantName and tenant name value.
- Create an environment and name it QA, we can add approvals here or you can skip this part.
- Now in Azure DevOps create a new pipeline and point it to the YML file, and validate it.

{% include article-ads.html %}

#### Conclusion

Hope this blog post will help you automate the custom policies, if you face any issues please leave a comment here.
cheers.

## Related posts

- [Automate Draw.io Diagram Export with Azure DevOps](/posts/automate-drawio-azure-devops/)
- [Securing Azure APIM With Azure Key Vault](/posts/APIM-Key-Vault/)
- [Terraform for developers](/posts/TF-For-Developers/)
