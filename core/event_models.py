from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _


class BaseModel(models.Model):
    """
    Reusable abstract model for important system records.

    It records:
    - whether the record is active;
    - who created it;
    - who last updated it;
    - when it was created;
    - when it was last updated.
    """

    is_active = models.BooleanField(
        _("is active"),
        default=True,
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("created by"),
        related_name="%(app_label)s_%(class)s_created_records",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        editable=False,
    )

    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("updated by"),
        related_name="%(app_label)s_%(class)s_updated_records",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        editable=False,
    )

    created_at = models.DateTimeField(
        _("created at"),
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        _("updated at"),
        auto_now=True,
    )

    class Meta:
        abstract = True

from django.utils.text import slugify


class Country(BaseModel):
    name_sw = models.CharField(
        _("name in Kiswahili"),
        max_length=100,
        unique=True,
    )

    name_en = models.CharField(
        _("name in English"),
        max_length=100,
        unique=True,
    )

    code = models.CharField(
        _("country code"),
        max_length=3,
        unique=True,
        help_text=_("Use the ISO country code, for example TZA."),
    )

    phone_code = models.CharField(
        _("phone code"),
        max_length=10,
        blank=True,
        help_text=_("For example +255."),
    )

    slug = models.SlugField(
        _("slug"),
        max_length=120,
        unique=True,
        blank=True,
    )

    class Meta:
        verbose_name = _("country")
        verbose_name_plural = _("countries")
        ordering = ["name_en"]

    def save(self, *args, **kwargs):
        self.code = self.code.strip().upper()

        if not self.slug:
            self.slug = slugify(self.name_en or self.name_sw)

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name_sw} / {self.name_en}"


class Region(BaseModel):
    country = models.ForeignKey(
        Country,
        verbose_name=_("country"),
        related_name="regions",
        on_delete=models.PROTECT,
    )

    name_sw = models.CharField(
        _("name in Kiswahili"),
        max_length=100,
    )

    name_en = models.CharField(
        _("name in English"),
        max_length=100,
    )

    code = models.CharField(
        _("region code"),
        max_length=20,
    )

    slug = models.SlugField(
        _("slug"),
        max_length=140,
        blank=True,
    )

    class Meta:
        verbose_name = _("region")
        verbose_name_plural = _("regions")
        ordering = ["name_sw"]

        constraints = [
            models.UniqueConstraint(
                fields=["country", "code"],
                name="unique_region_code_per_country",
            ),
            models.UniqueConstraint(
                fields=["country", "name_sw"],
                name="unique_region_name_sw_per_country",
            ),
            models.UniqueConstraint(
                fields=["country", "name_en"],
                name="unique_region_name_en_per_country",
            ),
        ]

    def save(self, *args, **kwargs):
        self.code = self.code.strip().upper()

        if not self.slug:
            self.slug = slugify(
                f"{self.country.code}-{self.name_en or self.name_sw}"
            )

        super().save(*args, **kwargs)

    def __str__(self):
        return self.name_sw


class District(BaseModel):
    region = models.ForeignKey(
        Region,
        verbose_name=_("region"),
        related_name="districts",
        on_delete=models.PROTECT,
    )

    name_sw = models.CharField(
        _("name in Kiswahili"),
        max_length=120,
    )

    name_en = models.CharField(
        _("name in English"),
        max_length=120,
    )

    code = models.CharField(
        _("district code"),
        max_length=30,
    )

    slug = models.SlugField(
        _("slug"),
        max_length=160,
        blank=True,
    )

    class Meta:
        verbose_name = _("district")
        verbose_name_plural = _("districts")
        ordering = ["name_sw"]

        constraints = [
            models.UniqueConstraint(
                fields=["region", "code"],
                name="unique_district_code_per_region",
            ),
            models.UniqueConstraint(
                fields=["region", "name_sw"],
                name="unique_district_name_sw_per_region",
            ),
            models.UniqueConstraint(
                fields=["region", "name_en"],
                name="unique_district_name_en_per_region",
            ),
        ]

    def save(self, *args, **kwargs):
        self.code = self.code.strip().upper()

        if not self.slug:
            self.slug = slugify(
                f"{self.region.code}-{self.name_en or self.name_sw}"
            )

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name_sw} - {self.region.name_sw}"


class Council(BaseModel):
    class CouncilType(models.TextChoices):
        CITY = "CITY", _("City Council")
        MUNICIPAL = "MUNICIPAL", _("Municipal Council")
        TOWN = "TOWN", _("Town Council")
        DISTRICT = "DISTRICT", _("District Council")
        ZANZIBAR_MUNICIPAL = (
            "ZANZIBAR_MUNICIPAL",
            _("Municipal Council - Zanzibar"),
        )
        ZANZIBAR_TOWN = (
            "ZANZIBAR_TOWN",
            _("Town Council - Zanzibar"),
        )
        ZANZIBAR_DISTRICT = (
            "ZANZIBAR_DISTRICT",
            _("District Council - Zanzibar"),
        )
        OTHER = "OTHER", _("Other")

    region = models.ForeignKey(
        Region,
        verbose_name=_("region"),
        related_name="councils",
        on_delete=models.PROTECT,
    )

    district = models.ForeignKey(
        District,
        verbose_name=_("district"),
        related_name="councils",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        help_text=_("Optional district grouping within the selected region."),
    )

    name_sw = models.CharField(
        _("name in Kiswahili"),
        max_length=160,
    )

    name_en = models.CharField(
        _("name in English"),
        max_length=160,
    )

    code = models.CharField(
        _("council code"),
        max_length=40,
    )

    council_type = models.CharField(
        _("council type"),
        max_length=30,
        choices=CouncilType.choices,
        default=CouncilType.DISTRICT,
    )

    slug = models.SlugField(
        _("slug"),
        max_length=200,
        blank=True,
    )

    class Meta:
        verbose_name = _("council")
        verbose_name_plural = _("councils")
        ordering = ["region__name_sw", "name_sw"]

        constraints = [
            models.UniqueConstraint(
                fields=["region", "code"],
                name="unique_council_code_per_region",
            ),
            models.UniqueConstraint(
                fields=["region", "name_sw"],
                name="unique_council_name_sw_per_region",
            ),
        ]

    def save(self, *args, **kwargs):
        self.code = self.code.strip().upper()

        if not self.slug:
            self.slug = slugify(
                f"{self.region.code}-{self.name_en or self.name_sw}"
            )

        self.full_clean()
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        if self.district_id and self.region_id and self.district.region_id != self.region_id:
            raise ValidationError({
                "district": _("The district must belong to the selected region."),
            })

    def __str__(self):
        return f"{self.name_sw} - {self.region.name_sw}"


class Ward(BaseModel):
    council = models.ForeignKey(
        Council, verbose_name=_("council"), related_name="wards",
        on_delete=models.PROTECT,
    )
    name_sw = models.CharField(_("name in Kiswahili"), max_length=160)
    name_en = models.CharField(_("name in English"), max_length=160)
    code = models.CharField(_("ward code"), max_length=50)
    slug = models.SlugField(_("slug"), max_length=220, blank=True)

    class Meta:
        verbose_name = _("ward")
        verbose_name_plural = _("wards")
        ordering = ["council__region__name_sw", "council__name_sw", "name_sw"]
        constraints = [models.UniqueConstraint(
            fields=["council", "code"], name="unique_ward_code_per_council",
        )]

    def save(self, *args, **kwargs):
        self.code = self.code.strip().upper()
        if not self.slug:
            self.slug = slugify(
                f"{self.council.code}-{self.name_en or self.name_sw}"
            )
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name_sw} - {self.council.name_sw}"

