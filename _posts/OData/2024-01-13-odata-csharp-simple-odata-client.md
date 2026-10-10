---
layout: post
title: "Simple OData Client - Dotnet 8 and C#"
description: "An overview of Simple.OData.Client for C# and .NET: setup, querying OData services with a fluent API, and its advantages and disadvantages."
date: 2024-01-13 00:00:00 +0100
categories: coding odata dotnet d365
tags: odata csharp dotnet simple.odata.client httpclient d365
author: manishtiwari25
image:
  path: /assets/img/headers/simple-odata.webp
  alt: "OData logo on a light grey, angular geometric background, header for the Simple.OData.Client in .NET 8 post"
---

Simple.OData.Client is a multi-platform OData client library supporting .NET 4.x, netstandard 2.0, Android, and iOS. The adapter provides a great alternative to the WCF Data Services client. It does not require the generation of context or entity classes and fits the RESTful nature of OData services.

> **Which OData client library is this?** This post covers the community **Simple.OData.Client** NuGet package, which needs no code generation. If you prefer Microsoft's typed, metadata-generated client, read the sibling post on [OData Connected Service / OData Client](/posts/odata-csharp-odata-client/) - it uses the same TripPin sample service, so the two walkthroughs are directly comparable. Latency numbers for both (plus raw `HttpClient`) are in the [OData client benchmark](/posts/odata-csharp-benchmark/).
{: .prompt-info }

## How to integrate in c#

- Add Simple.OData.Client NuGet package

```bash

dotnet add package Simple.OData.Client

```

- Create a model class, In this example we will be creating `People.cs`

```cs

public class People
{
    public string UserName { get; set; }
    public string FirstName { get; set; }
    public string LastName { get; set; }
    public string MiddleName { get; set; }
    public string Gender { get; set; }
    public string Age { get; set; }
    public List<string> Emails { get; set; }
    public List<AddressInfo> AddressInfo { get; set; }
    public AddressInfo HomeAddress { get; set; }
    public long Concurrency => new();
}
public class AddressInfo
{
    public string Address { get; set; }
    public AddressCityInfo City { get; set; }
}
public class AddressCityInfo
{
   public string Name { get; set; }
    public string CountryRegion { get; set; }
    public string Region { get; set; }
}
```

- In `Program.cs` Add the following

```cs

using Simple.OData.Client;

public class Main
{
  public static void Main(string[] s)
  {
      var baseUrl = "https://services.odata.org/V4/(S(y5tuj04bxbfsxzimbxbnauqg))/TripPinServiceRW/";
      var client = new ODataClient(baseUrl);

      var dataEnum = await _client
           .For<People>("People")
           .FindEntriesAsync();
        var data = dataEnum.ToList();

  }
}

```

![OData query request to the People entity set and the JSON response with @odata.context and the value array returned by FindEntriesAsync](/assets/img/posts/odata/odata-query-request-and-response.webp){: width="1920" height="1040" }

- In case of Simple.OData.Client, the initial load time can be more, the library tries to fetch the metadata and use it for the validation later.

Official [GitHub Repo](https://github.com/simple-odata-client/Simple.OData.Client).
you can get the code [here](https://github.com/lamplitlabs/bites-in-byte-blog/blob/main/src/ODataBenchmark/BenchmarkSimpleODataClient.cs)

## Advantages of Simple OData Client

- #### Ease of Use

Simple OData Client is a straightforward and easy-to-use library that requires minimal coding compared to other OData clients. It provides a simplified API for basic OData operations, making it suitable for developers with limited OData experience.

- #### Self-Contained

Simple OData Client is a self-contained library that doesn't require additional dependencies or third-party libraries. This makes it lightweight and portable, making it easy to integrate into existing projects.

- #### No Dependency on OData Metadata

Simple OData Client does not require OData metadata to function. It can parse and consume OData responses without the need for predefined metadata descriptions.

- #### Customizable Data Mapping

Simple OData Client provides a flexible data mapping mechanism that allows developers to customize how OData data is mapped to custom C# classes. This enables finer control over data representation and manipulation.

- #### Support for Various Data Providers

Simple OData Client supports various data providers, including OData services, Web APIs, and embedded data resources. This makes it versatile for connecting to different data sources.

## Disadvantages of Simple OData Client

- #### Limited Features

Simple OData Client is more limited in features compared to more comprehensive OData client libraries. It may lack support for advanced OData features, such as complex queries, batch operations, or custom service operations.

- #### Manual Parsing

Simple OData Client requires manual parsing of OData responses to extract and process data. This can be more time-consuming and error-prone compared to libraries that automate this process.

- #### Reduced Developer Productivity

The manual nature of Simple OData Client may reduce developer productivity compared to more streamlined libraries. Developers may need to invest more time in handling low-level details, hindering overall development efficiency.

- #### Limited Community Support

Simple OData Client has a smaller community compared to more established OData client libraries. This may mean fewer resources available for troubleshooting and support.

- #### Potential for Errors

Manual parsing and data manipulation in Simple OData Client introduce more opportunities for errors compared to libraries that handle these tasks automatically. Developers need to carefully handle and validate data to prevent issues.

## Conclusion

In summary, Simple OData Client is a lightweight and easy-to-use library that is suitable for simple OData interactions. However, its limited features, manual parsing, and reduced developer productivity may make it less suitable for complex OData scenarios or projects with tight development timelines. For more advanced OData development, consider using other OData client libraries that offer a wider range of features and abstraction.

## Other

If you want to explore your OData metadata, you can visit an [open-source](https://edmx.lamplitlabs.com/#/explore) project created by me. By using this tool you can get the data types, enum values, and other useful information.

## Related posts

- [Navigating OData APIs with Dotnet 8 and C#: Exploring Options and Drawbacks](/posts/odata/)
- [OData Client- Dotnet 8 and C#](/posts/odata-csharp-odata-client/)
- [Benchmarking OData Clients in Dotnet 8](/posts/odata-csharp-benchmark/)
