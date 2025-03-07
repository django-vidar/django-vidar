from django import template


register = template.Library()


@register.filter
def crontab_link_to_crontab_guru(crontab):
    fixed_crontab = crontab.replace(" ", "_")
    return f"https://crontab.guru/#{fixed_crontab}"
