package quota

import (
	"reflect"
	"testing"
)

func TestPage(t *testing.T) {
	items := []int{1, 2, 3, 4, 5, 6, 7}
	cases := []struct {
		page, size int
		want       []int
	}{
		{1, 3, []int{1, 2, 3}},
		{2, 3, []int{4, 5, 6}},
		{3, 3, []int{7}},
		{4, 3, []int{}},
	}
	for _, c := range cases {
		got, err := Page(items, c.page, c.size)
		if err != nil {
			t.Fatal(err)
		}
		if !reflect.DeepEqual(got, c.want) {
			t.Errorf("Page(%d, %d) = %v, want %v", c.page, c.size, got, c.want)
		}
	}
}

func TestPageRejectsZero(t *testing.T) {
	if _, err := Page([]int{1}, 0, 3); err == nil {
		t.Fatal("page 0 accepted")
	}
}
