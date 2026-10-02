---
layout: post
title: "Should we move to c# 8 using-declaration?"
description: "What C# 8 using declarations change compared to classic using blocks, when the object gets disposed, and whether moving your code to them is worth it."
date: 2020-02-04 09:00:00 -0500
categories: coding dotnet
tags: c# dotnet
author: manishtiwari25
image:
  path: /assets/img/headers/dotnet/csharp-using-declaration.webp
  alt: Code screenshot comparing the classic C# using statement block with the C# 8 using declaration
redirect_from:
  - /should-we-move-to-c-8-using-declaration-891e3866d81?source=post_internal_links---------0----------------------------
  - /should-we-move-to-c-8-using-declaration-891e3866d81?source=author_recirc-----a9c256fee353----4----------------------------
  - /should-we-move-to-c-8-using-declaration-891e3866d81
---

C# 8 officially got released on 23rd Sep 2019 and It has several new features.

![Stock photo of a developer workspace with a laptop keyboard on a desk, used as the article illustration](/assets/img/posts/csharp-using-developer-workspace.webp)

Today we will talk about one of the new feature using-declaration.

As we all know the traditional using statement is making developers life easier for a long time, it automatically disposes of the object without writing a single line of code.

First, let’s take a look into the traditional using statement, let say I have a class which implements the IDisposable interface (as shown in image).

```cs

//A class
public class SomeDisposableType : IDisposable
{
   ...implmentation details...
}


//traditional using statement
using (SomeDisposableType u = new SomeDisposableType())
{
    OperateOnType(u);
  	//u.Dipose is called
}
```

{% include article-ads.html %}
The using statement can be used to reference a variable or the result from a method, and at the end of the scope Dispose method gets invoked

behinds the scenes, compile creates the code using try/finally (as shown in image).

```cs

SomeDisposableType t = new SomeDisposableType();
try
{
    OperateOnType(t);
}
finally
{
    if (t != null)
    {
        ((IDisposable)t).Dispose();
    }
}
```

In c# 8, the code of using statement can be simplified. curly braces are no longer needed, the end of the block will be the scope of the variable and compiler makes try/finally block to make sure the object is disposed.

```cs

public class SomeDisposableType : IDisposable
{
   ...implmentation details...
}



//c# 8 feature
using var u = new SomeDisposableType();
OperateOnType(u);
```

{% include article-ads.html %}
if you use nested using statement your code will look like stairs with lots of curly braces, and it's hard to keep track of scops.

```cs
public class SomeDisposableType : IDisposable
{
   ...implmentation details...
}
public class SomeOtherDisposableType : IDisposable
{
   ...implmentation details...
}

using (var u = new SomeDisposableType()){
  	using (var v = new SomeOtherDisposableType()){
  		OperateOnType(u);
	}
}
```

let’s do the same with the new using-declaration. The following code is even shorter compared to the previous one — no matter how many resources you need to dispose.

```cs
public class SomeDisposableType : IDisposable{
   ...implmentation details...
}
public class SomeOtherDisposableType : IDisposable{
   ...implmentation details...
}
public void SomeMethod(){
using var u = new SomeDisposableType();
using var v = new SomeOtherDisposableType();
OperateOnType(u);
OperateOnType(v);
//u.dispose
//v.dispose
}
```

it looks a small feature, but this can make code cleaner and less buggy.

if the method is small, then we should definitely use simplified using and it also helps the compiler, now compiler doest have to keep track of all the scopes.

I think I’ll switch to the new using-declaration with all my code and hope you will do the same.
