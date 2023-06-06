from django.shortcuts import render, get_object_or_404, redirect
from django.views.generic import ListView, DetailView, View
from .models import Item, Order, OrderItem, BillingAddress, Payment
from django.conf import settings
from .forms import CheckoutForm
from django.utils import timezone
from django.contrib import messages
from django.core.exceptions import ObjectDoesNotExist
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin

# Create your views here.
import stripe
stripe.api_key = getattr(settings, "STRIPE_SECRET_KEY", "")



def products(request):
    context = {
        "items" : Item.objects.all()
    }
    return render(request, "products.html", context)

class CheckoutView(View):
    def get(self, *args, **kwargs):
        #form
        form = CheckoutForm()
        context = {
            'form': form
        }
        return render(self.request, 'checkout.html', context)
    
    def post(self, *args, **kwargs):
        form = CheckoutForm(self.request.POST or None)
        try:
            order = Order.objects.get(user=self.request.user, ordered=False)
            if form.is_valid():
                street_address = form.cleaned_data.get('street_address')
                apartment_address = form.cleaned_data.get('apartment_address')
                billing_country = form.cleaned_data.get('billing_country')
                zip = form.cleaned_data.get('zip')
                # same_billing_address = form.cleaned_data.get('same_billing_address')
                # save_info = form.cleaned_data.get('save_info')
                payment_option = form.cleaned_data.get('payment_option')
                billing_address = BillingAddress(
                    user = self.request.user,
                    street_address = street_address,
                    apartment_address = apartment_address,
                    country = billing_country,
                    zip = zip
                )
                billing_address.save()
                order.billing_address = billing_address
                order.save()

                if payment_option == 'S':
                    return redirect('core:payment', payment_option='stripe')
                elif payment_option == 'P':
                    return redirect('core:payment', payment_option='paypal')
                else:
                    messages.warning(self.request, "Invalid Payment Option Selected")
                    return redirect('core:checkout')         
        except ObjectDoesNotExist:
            messages.error(self.request, "You do not have an active order")
            return redirect("core:order-summary")
        

class PaymentView(View):
    def get(self, *args, **kwargs):
        #order
        order = Order.objects.get(user=self.request.user, ordered=False)
        context = {
            "order": order
        }
        return render(self.request, "payment.html", context)
    
    def post(self, *args, **kwargs):
        order = Order.objects.get(user=self.request.user, ordered=False)
        token = self.request.POST.get('stripeToken')
        amount= int(order.get_total() * 100)

        try:
            charge = stripe.Charge.create(
                amount=amount,  #cents
                currency="usd",
                source=token,
            )

            payment = Payment()
            payment.stripe_charge_id = charge['id']
            payment.user = self.request.user
            payment.amount = order.get_total()
            payment.save()

            #assign payment to the order
            order.ordered = True
            order.payment = payment
            order.save()

            messages.success(self.request, "Your order was successful")
            return redirect("/")


        except stripe.error.CardError as e:
            # Since it's a decline, stripe.error.CardError will be caught
            body = e.json_body
            err = body.get('error', {})
            messages.warning(self.request, f"{err.get('message')}")
            return redirect("/")

        except stripe.error.RateLimitError as e:
            # Too many requests made to the API too quickly
            messages.warning(self.request, "Rate Limit error")
            return redirect("/")

        except stripe.error.InvalidRequestError as e:
            # Invalid parameters were supplied to Stripe's API
            messages.warning(self.request, "Invalid Parameters")
            return redirect("/")

        except stripe.error.AuthenticationError as e:
            # Authentication with Stripe's API failed
            # (maybe you changed API keys recently)
            messages.warning(self.request, "Not Authenticated")
            return redirect("/")

        except stripe.error.APIConnectionError as e:
            # Network communication with Stripe failed
            messages.warning(self.request, "Network Error")
            return redirect("/")

        except stripe.error.StripeError as e:
            # Display a very generic error to the user, and maybe send
            # yourself an email
            messages.warning(self.request, "Something went wrong. You were not charged, please try again")
            return redirect("/")

        except Exception as e:
            # Something else happened, completely unrelated to Stripe
            #send an email to ourself
            messages.warning(self.request, "A serious error occured. We have been notified")
            return redirect("/")



        

        
        


class HomeView(ListView):
    model = Item
    paginate_by = 10
    template_name = "home.html"


class OrderSummaryView(LoginRequiredMixin, View):
    def get(self, *args, **kwargs):
        try:
            order = Order.objects.get(user=self.request.user, ordered=False)
            context = {
                "object": order
            }
            return render(self.request, 'order-summary.html', context)
        except ObjectDoesNotExist:
            messages.error(self.request, "You do not have an active order")
            return redirect("/")

        

class ItemDetailView(DetailView):
    model = Item
    template_name = "product.html"

@login_required
def add_to_cart(request, slug):
    item = get_object_or_404(Item, slug=slug)
    order_item, created = OrderItem.objects.get_or_create(
        item=item,
        user=request.user,
        ordered=False
    )
    order_qs = Order.objects.filter(user=request.user, ordered=False)
    if order_qs.exists():
        order = order_qs[0]
        if order.items.filter(item__slug=item.slug).exists():
            order_item.quantity += 1
            order_item.save()
            messages.info(request, "This item quantity was updated ")
            return redirect("core:order-summary")
        else:
            messages.info(request, "This item was added to your cart.")
            order.items.add(order_item)
            return redirect("core:order-summary")
    else:
        ordered_date = timezone.now()
        order = Order.objects.create(user=request.user, ordered_date=ordered_date)
        order.items.add(order_item)
        messages.info(request, "This item was added to your cart.")
        return redirect("core:order-summary")

@login_required
def remove_from_cart(request, slug):
    item = get_object_or_404(Item, slug=slug)
    order_qs = Order.objects.filter(user=request.user, ordered=False)
    if order_qs.exists():
        order = order_qs[0]
        if order.items.filter(item__slug=item.slug).exists():
            order_item = OrderItem.objects.filter(
                item=item,
                user=request.user,
                ordered=False
            )[0]
            order.items.remove(order_item)
            messages.info(request, "This item was removed from your cart")
            return redirect("core:order-summary")
        else:
            # add a message saying user doesnt have an order
            messages.info(request, "This item was not in your cart")
            return redirect("core:product", slug=slug)
    else:
        # add a message saying user doesnt have an order
        messages.info(request, "You do not have an active order")
        return redirect("core:product", slug=slug)
    
@login_required
def remove_single_item_from_cart(request, slug):
    item = get_object_or_404(Item, slug=slug)
    order_qs = Order.objects.filter(user=request.user, ordered=False)
    if order_qs.exists():
        order = order_qs[0]
        if order.items.filter(item__slug=item.slug).exists():
            order_item = OrderItem.objects.filter(
                item=item,
                user=request.user,
                ordered=False
            )[0]
            if order_item.quantity > 1:
                order_item.quantity -= 1
                order_item.save()
            else:
                order.items.remove(order_item)
            messages.info(request, "This item quantity was updated")
            return redirect("core:order-summary")
        else:
            # add a message saying user doesnt have an order
            messages.info(request, "This item was not in your cart")
            return redirect("core:product", slug=slug)
    else:
        # add a message saying user doesnt have an order
        messages.info(request, "You do not have an active order")
        return redirect("core:product", slug=slug)