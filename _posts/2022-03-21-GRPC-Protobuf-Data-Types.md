---
layout: post
title: "gRPC Protobuf Data Types"
date: 2022-03-21 09:00:00 -0500
categories: coding grpc
tags: grpc grpc-data-type
author: manishtiwari25
image:
  path: /assets/img/headers/grpc-protobuf-data-types.webp
  alt: Sample .proto file listing gRPC protobuf scalar and well-known data types
redirect_from:
  - /grpc-protobuf-data-types-7148ce60b54b?source=user_profile---------7----------------------------
  - /grpc-protobuf-data-types-7148ce60b54b
  - /share?text=gRPC Protobuf Data Types - Lamplit Labs https://blogs.lamplitlabs.com/posts/GRPC-Protobuf-Data-Types/
---

the goal of this article is to get a complete list of gRPC data type in a single document, kind of cheat sheet.

There are 3 type of protobuf data types

1. Scalar Value types
2. Well known types
3. Google common types
4. Custom types

{% include article-ads.html %}

<h4>Scalar Value types</h4>
these are common data types used in protobuf. scalar data type does not support null values.
you can find more complete list [here](https://developers.google.com/protocol-buffers/docs/proto3#scalar) .

```
syntax = "proto3"
message Something {
   string subject = 1;
   int32 id = 2;
   float floatVar = 3;
}
```

<h4>Well known types</h4>
there are more advance types provided by google. these supports null values.
you can find complete list [here](https://developers.google.com/protocol-buffers/docs/reference/google.protobuf)
For using these you have to import them.

```
syntax = "proto3"

import "google/protobuf/duration.proto";
import "google/protobuf/timestamp.proto";
import "google/protobuf/wrappers.proto"
message Meeting {

    google.protobuf.StringValue subject = 1;
    google.protobuf.Timestamp time = 2;
    google.protobuf.Duration duration = 3;

}

```

{% include feed-ads.html %}

<h4>Google common types</h4>
there are few custom data types provided by google, these are specially made for advance cases like money, phone number etc. if you want to use them just copy the proto file and put it into your project and import it.
you can find all the implementation [here](https://github.com/googleapis/googleapis/tree/master/google/type)

<h4>Custom types</h4>
google common types are kind of custom types, you can create your own proto file and define something there and use it.

you can just refer to one of the google common type.

{% include article-ads.html %}

<h4>Addition Links</h4>
- https://docs.microsoft.com/en-us/dotnet/architecture/grpc-for-wcf-developers/protobuf-data-types
- https://developers.google.com/protocol-buffers/docs/proto3?source=post_page-----7148ce60b54b--------------------------------
- https://developers.google.com/protocol-buffers/docs/reference/google.protobuf?source=post_page-----7148ce60b54b--------------------------------
