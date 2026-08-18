from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("core", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name='Country',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('is_active', models.BooleanField(default=True, verbose_name='is active')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='created at')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='updated at')),
                ('name_sw', models.CharField(max_length=100, unique=True, verbose_name='name in Kiswahili')),
                ('name_en', models.CharField(max_length=100, unique=True, verbose_name='name in English')),
                ('code', models.CharField(help_text='Use the ISO country code, for example TZA.', max_length=3, unique=True, verbose_name='country code')),
                ('phone_code', models.CharField(blank=True, help_text='For example +255.', max_length=10, verbose_name='phone code')),
                ('slug', models.SlugField(blank=True, max_length=120, unique=True, verbose_name='slug')),
                ('created_by', models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='%(app_label)s_%(class)s_created_records', to=settings.AUTH_USER_MODEL, verbose_name='created by')),
                ('updated_by', models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='%(app_label)s_%(class)s_updated_records', to=settings.AUTH_USER_MODEL, verbose_name='updated by')),
            ],
            options={
                'verbose_name': 'country',
                'verbose_name_plural': 'countries',
                'ordering': ['name_en'],
            },
        ),
        migrations.CreateModel(
            name='Region',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('is_active', models.BooleanField(default=True, verbose_name='is active')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='created at')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='updated at')),
                ('name_sw', models.CharField(max_length=100, verbose_name='name in Kiswahili')),
                ('name_en', models.CharField(max_length=100, verbose_name='name in English')),
                ('code', models.CharField(max_length=20, verbose_name='region code')),
                ('slug', models.SlugField(blank=True, max_length=140, verbose_name='slug')),
                ('country', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='regions', to='core.country', verbose_name='country')),
                ('created_by', models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='%(app_label)s_%(class)s_created_records', to=settings.AUTH_USER_MODEL, verbose_name='created by')),
                ('updated_by', models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='%(app_label)s_%(class)s_updated_records', to=settings.AUTH_USER_MODEL, verbose_name='updated by')),
            ],
            options={
                'verbose_name': 'region',
                'verbose_name_plural': 'regions',
                'ordering': ['name_sw'],
            },
        ),
        migrations.CreateModel(
            name='District',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('is_active', models.BooleanField(default=True, verbose_name='is active')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='created at')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='updated at')),
                ('name_sw', models.CharField(max_length=120, verbose_name='name in Kiswahili')),
                ('name_en', models.CharField(max_length=120, verbose_name='name in English')),
                ('code', models.CharField(max_length=30, verbose_name='district code')),
                ('slug', models.SlugField(blank=True, max_length=160, verbose_name='slug')),
                ('created_by', models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='%(app_label)s_%(class)s_created_records', to=settings.AUTH_USER_MODEL, verbose_name='created by')),
                ('region', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='districts', to='core.region', verbose_name='region')),
                ('updated_by', models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='%(app_label)s_%(class)s_updated_records', to=settings.AUTH_USER_MODEL, verbose_name='updated by')),
            ],
            options={
                'verbose_name': 'district',
                'verbose_name_plural': 'districts',
                'ordering': ['name_sw'],
            },
        ),
        migrations.AddConstraint(
            model_name='region',
            constraint=models.UniqueConstraint(fields=('country', 'code'), name='unique_region_code_per_country'),
        ),
        migrations.AddConstraint(
            model_name='region',
            constraint=models.UniqueConstraint(fields=('country', 'name_sw'), name='unique_region_name_sw_per_country'),
        ),
        migrations.AddConstraint(
            model_name='region',
            constraint=models.UniqueConstraint(fields=('country', 'name_en'), name='unique_region_name_en_per_country'),
        ),
        migrations.AddConstraint(
            model_name='district',
            constraint=models.UniqueConstraint(fields=('region', 'code'), name='unique_district_code_per_region'),
        ),
        migrations.AddConstraint(
            model_name='district',
            constraint=models.UniqueConstraint(fields=('region', 'name_sw'), name='unique_district_name_sw_per_region'),
        ),
        migrations.AddConstraint(
            model_name='district',
            constraint=models.UniqueConstraint(fields=('region', 'name_en'), name='unique_district_name_en_per_region'),
        ),
        migrations.CreateModel(
            name='Council',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('is_active', models.BooleanField(default=True, verbose_name='is active')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='created at')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='updated at')),
                ('name_sw', models.CharField(max_length=160, verbose_name='name in Kiswahili')),
                ('name_en', models.CharField(max_length=160, verbose_name='name in English')),
                ('code', models.CharField(max_length=40, verbose_name='council code')),
                ('council_type', models.CharField(choices=[('CITY', 'City Council'), ('MUNICIPAL', 'Municipal Council'), ('TOWN', 'Town Council'), ('DISTRICT', 'District Council'), ('ZANZIBAR_MUNICIPAL', 'Municipal Council - Zanzibar'), ('ZANZIBAR_TOWN', 'Town Council - Zanzibar'), ('ZANZIBAR_DISTRICT', 'District Council - Zanzibar'), ('OTHER', 'Other')], default='DISTRICT', max_length=30, verbose_name='council type')),
                ('slug', models.SlugField(blank=True, max_length=200, verbose_name='slug')),
                ('created_by', models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='%(app_label)s_%(class)s_created_records', to=settings.AUTH_USER_MODEL, verbose_name='created by')),
                ('region', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='councils', to='core.region', verbose_name='region')),
                ('updated_by', models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='%(app_label)s_%(class)s_updated_records', to=settings.AUTH_USER_MODEL, verbose_name='updated by')),
            ],
            options={
                'verbose_name': 'council',
                'verbose_name_plural': 'councils',
                'ordering': ['region__name_sw', 'name_sw'],
            },
        ),
        migrations.AddConstraint(
            model_name='council',
            constraint=models.UniqueConstraint(fields=('region', 'code'), name='unique_council_code_per_region'),
        ),
        migrations.AddConstraint(
            model_name='council',
            constraint=models.UniqueConstraint(fields=('region', 'name_sw'), name='unique_council_name_sw_per_region'),
        ),
    ]
