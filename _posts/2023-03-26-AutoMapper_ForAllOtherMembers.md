---
layout: post
title: "AutoMapper ForAllOtherMembers"
date: 2023-03-26 09:00:00 -0500
categories: coding dotnet
tags: .NET7 .NET8 c# AutoMapper
author: manishtiwari25
redirect_from:
  - /blogPost/9a27ad88-0d31-4618-b2d1-9555edbbaa80/automapper-forallothermembers
  - /blogPost/9a27ad88-0d31-4618-b2d1-9555edbbaa80
  - /share?text=AutoMapper ForAllOtherMembers - Lamplit Labs https://blogs.lamplitlabs.com/posts/AutoMapper_ForAllOtherMembers/
image:
  path: /assets/img/headers/automapper.webp
---

`ForAllOtherMembers` was removed <br>
That was used to disable mapping by convention, not something we want to support.
<br>
AutoMapper 11 came with a breaking change, which we all hate. I hope this blog post will end your search.

After digging into Stackoverflow and Internet, I found a dirty way to work with the breaking change.

{% include article-ads.html %}

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

{% include article-ads.html %}

there are more ways which you can find in [this stack overflow](https://stackoverflow.com/questions/71311303/replacement-for-automappers-forallothermembers) article.
<br>

{% include feed-ads.html %}

**PS: I would not recommend this, because this method goes against the [auto mapper's design philosophy](https://jimmybogard.com/automappers-design-philosophy/).** <br>
As mentioned in the [GitHub discussion](https://github.com/AutoMapper/AutoMapper/discussions/4036), the author of AutoMapper **"regrets ever adding it in the first place"**.
<br>
Cheers <br>
Happy coding :)
