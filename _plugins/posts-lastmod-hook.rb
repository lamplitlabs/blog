#!/usr/bin/env ruby
#
# Check for changed posts
#
# One `git log` over _posts at load time replaces two git subprocesses per
# post, so a full build no longer spends most of its time forking git.
# Semantics are unchanged: a post gets `last_modified_at` only when it has
# more than one commit, and the value is the date of its latest commit.

module PostsLastmod
  # path (repo-relative) => [latest commit date, commit count]
  def self.index
    @index ||= build_index
  end

  def self.build_index
    index = Hash.new { |h, k| h[k] = [nil, 0] }
    out = `git log --name-only --pretty=format:%x00%ad --date=iso -- _posts`
    return index unless $?.success?

    current = nil
    out.each_line(chomp: true) do |line|
      next if line.empty?

      if line.start_with?("\0")
        current = line[1..]
      elsif current
        entry = index[line]
        entry[0] ||= current # log is newest-first, keep first seen
        entry[1] += 1
      end
    end
    index
  end
end

Jekyll::Hooks.register :posts, :post_init do |post|
  # git prints repo-relative paths; Document#relative_path is relative to the
  # site source, which is the repository root here.
  date, count = PostsLastmod.index[post.relative_path]
  next unless count && count > 1

  post.data['last_modified_at'] = date
end
