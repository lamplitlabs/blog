---
layout: post
title: "GCP Authentication Without JSON file"
date: 2023-03-25 09:00:00 -0500
categories: coding cloud dotnet
tags: .NET7 .NET8 c# Firebase GCP
author: manishtiwari25
redirect_from:
  - /blogPost/cb792a32-945b-4f21-b57d-81ab5fffeeda/gcp-authentication-without-json-file
  - /blogPost/cb792a32-945b-4f21-b57d-81ab5fffeeda
image:
  path: /assets/img/headers/gcp.webp
---

In this blog post, I will explain how we can authenticate GCP or Firebase without storing JSON in your repository.<br>

**TL/DR**
<br>
If you are just interested in code, you can just visit the [GitHub](https://github.com/lamplitlabs/bites-in-byte-blog/tree/main/src/GcpWithoutJson) repository.
The code is compatible with **.NET 7**.

{% include feed-ads.html %}

<br>
Recently I got a chance to work on Firebase with .Net 7. all over the internet all the docs were saying to add the JSON file and then connect. <br>
In my case, I had to use Azure Key vault with an [option pattern](https://learn.microsoft.com/en-us/dotnet/core/extensions/options). <br>
after digging throw the docs and reading over the internet, I was able to use IConfiguration. <br>

In the example, I am using Firestore, but I think it should work with all other services. <br>

First thing first, we need to add some NuGets

{% include article-ads.html %}

```cs
Google.Cloud.Channel.V1
Google.Cloud.Firestore
```

After that, Add a class called `GCPCredentials.cs`

```cs
using System.Text.Json.Serialization;
namespace GcpWithoutJson;
public class GCPCredentials
{
    [JsonPropertyName("type")]
    public string Type { get; set; }

    [JsonPropertyName("private_key")]
    public string PrivateKey { get; set; }

    [JsonPropertyName("private_key_id")]
    public string PrivateKeyId { get; set; }

    [JsonPropertyName("project_id")]
    public string ProjectId { get; set; }

    [JsonPropertyName("client_email")]
    public string ClientEmail { get; set; }

    [JsonPropertyName("client_id")]
    public string ClientId { get; set; }

    [JsonPropertyName("auth_uri")]
    public string AuthURI { get; set; }

    [JsonPropertyName("token_uri")]
    public string TokenURI { get; set; }

    [JsonPropertyName("auth_provider_x509_cert_url")]
    public string AuthProviderCertURL { get; set; }

    [JsonPropertyName("client_x509_cert_url")]
    public string ClientCertURL { get; set; }
}
```

Add following section on you `appsettings.json` file

```json
 "GCP": {
    "Type": "service_account",
    "PrivateKey": "",
    "PrivateKeyId": "",
    "ProjectId": "",
    "ClientEmail": "",
    "ClientId": "",
    "AuthURI": "",
    "TokenURI": "",
    "AuthProviderCertURL": "",
    "ClientCertURL": ""
  }
```

{% include article-ads.html %}

In the example, I am using a console application so I am creating configurations using `ConfigurationBuilder`. <br>
but if you are using Minimal API or Web app, you should use DI. <br>

```cs
 var builder = new ConfigurationBuilder()
                        .SetBasePath(Directory.GetCurrentDirectory())
                        .AddJsonFile("appsettings.json", optional: false);
var config = builder.Build();
var creds = new GCPCredentials();
config.GetSection("GCP").Bind(creds);
```

Now you are ready to connect to GCP. <br>
First, we need to create `GoogleCredential`

```cs
var credJson = JsonSerializer.Serialize(creds);
var gcpCreds = GoogleCredential.FromJson(credJson);
```

{% include article-ads.html %}
after this, the code is related to Firestore, but I think the approach should be similar to other services. <br>
create FirestoreDb using FirestoreDbBuilder <br>

```cs
var firestoreDbBuilder = new FirestoreDbBuilder
{
    ProjectId = creds.ProjectId,
    ChannelCredentials = gcpCreds.ToChannelCredentials()
};
var firestoreDb = await firestoreDbBuilder.BuildAsync();
```

{% include article-ads.html %}

Now your code is ready. you can add data to the Firestore collection.

```cs
await firestoreDb.Collection("blogs").AddAsync(new { Hello = "Hello World!!!" });
```

That's It!!! I hope it helps. <br>
Happy Coding :)
