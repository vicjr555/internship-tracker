from django.contrib.auth import login
from django.contrib.auth.forms import UserCreationForm
from django.shortcuts import redirect, render


def signup(request):
    """Create an account with Django's built-in form, then log the new user in."""
    if request.user.is_authenticated:
        return redirect("listings:list")

    form = UserCreationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        return redirect("listings:list")
    return render(request, "registration/signup.html", {"form": form})
