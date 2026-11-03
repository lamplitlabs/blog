---
layout: post
title: "AutoMapper ForAllOtherMembers"
description: "ForAllOtherMembers was removed from AutoMapper; here is why, and how to migrate mappings that relied on it."
date: 2023-03-26 00:00:00 +0100
categories: coding dotnet
tags: dotnet csharp AutoMapper
author: manishtiwari25
redirect_from:
  - /blogPost/9a27ad88-0d31-4618-b2d1-9555edbbaa80/automapper-forallothermembers
  - /blogPost/9a27ad88-0d31-4618-b2d1-9555edbbaa80
  - /share?text=AutoMapper ForAllOtherMembers - Lamplit Labs https://blogs.lamplitlabs.com/posts/AutoMapper_ForAllOtherMembers/
image:
  path: /assets/img/headers/automapper.webp
  alt: "AutoMapper header image for the ForAllOtherMembers removal and migration post"
---

`ForAllOtherMembers` was removed <br>
That was used to disable mapping by convention, not something we want to support.
<br>
AutoMapper 11 came with a breaking change, which we all hate. I hope this blog post will end your search.

After digging into Stackoverflow and Internet, I found a dirty way to work with the breaking change.

![Diff showing the AutoMapper ForAllOtherMembers call removed and replaced after the breaking change](/assets/img/posts/dotnet/automapper-forallothermembers-removed-diff.webp){: width="1280" height="678" }

Create an extension Method called `ForAllOtherMembers`.

```cs
 public static class AutomapperExtensions
 {
        private static readonly PropertyInfo TypeMapActionsProperty = typeof(TypeMapConfiguration).GetProperty("TypeMapActions", BindingFlags.NonPublic | BindingFlags.Instance);

        private static readonly PropertyInfo DestinationTypeDetailsProperty = typeof(TypeMap).GetProperty("DestinationTypeDetails", BindingFlags.NonPublic | BindingFlags.Instance);


        public static void ForAllOtherMembers<TSource, TDestination>(this IMappingExpression<TSource, TDestination> expression, Action<IMemberConfigurationExpression<TSource, TDestination, object>> memberOptions)
        {
            var typeMapConfiguration = (TypeMapConfiguration)expression;

            var typeMapActions = (List<Action<TypeMap>>)TypeMapActionsProperty.GetValue(typeMapConfiguration);

            typeMapActions.Add(typeMap =>
            {
                var destinationTypeDetails = (TypeDetails)DestinationTypeDetailsProperty.GetValue(typeMap);

                foreach (var accessor in destinationTypeDetails.WriteAccessors.Where(m => typeMapConfiguration.GetDestinationMemberConfiguration(m) == null))
                {
                    expression.ForMember(accessor.Name, memberOptions);
                }
            });
        }
 }
```

there are more ways which you can find in [this stack overflow](https://stackoverflow.com/questions/71311303/replacement-for-automappers-forallothermembers) article.
<br>

**PS: I would not recommend this, because this method goes against the [auto mapper's design philosophy](https://jimmybogard.com/automappers-design-philosophy/).** <br>
As mentioned in the [GitHub discussion](https://github.com/AutoMapper/AutoMapper/discussions/4036), the author of AutoMapper **"regrets ever adding it in the first place"**.
<br>
Cheers <br>
Happy coding :)

## Related posts

- [The Stirring Debate Surrounding Moq's Latest Version: Unveiling Privacy Concerns and Trust Dilemmas](/posts/Moq_Issue/)
- [Should we move to c# 8 using-declaration?](/posts/csharp-using/)
- [System.Text.Json Serialization Issue With Azure Cosmos DB SDK V3 For dotnet8](/posts/Cosmos_DB_Sdk_System_Text_Json_Issue/)
