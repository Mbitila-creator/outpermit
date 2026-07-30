from django import forms
from .models import SummitParticipant


class SummitParticipantForm(forms.ModelForm):
    class Meta:
        model = SummitParticipant
        fields = [
            'title',
            'other_title',
            'full_name',
            'institution',
            'designation',
            'phone',
            'email',
            'region',
            'attendance_type',
            'photo',
        ]

        widgets = {
            'title': forms.Select(attrs={
                'class': 'form-control',
                'id': 'id_title'
            }),
            'other_title': forms.TextInput(attrs={
                'class': 'form-control',
                'id': 'id_other_title',
                'placeholder': 'Enter other title'
            }),
            'full_name': forms.TextInput(attrs={'class': 'form-control'}),
            'institution': forms.TextInput(attrs={'class': 'form-control'}),
            'designation': forms.TextInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'region': forms.TextInput(attrs={'class': 'form-control'}),
            'attendance_type': forms.Select(attrs={'class': 'form-control'}),
            'photo': forms.FileInput(attrs={
                'class': 'form-control',
                'accept': 'image/*',
                'capture': 'user'
            }),
        }

        labels = {
            'title': 'Title',
            'other_title': 'Other Title',
            'full_name': 'Full Name',
            'institution': 'Institution',
            'designation': 'Designation',
            'phone': 'Phone',
            'email': 'Email',
            'region': 'Region',
            'attendance_type': 'Attendance Type',
            'photo': 'Photo',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['photo'].required = False
        self.fields['other_title'].required = False

        placeholder_fields = [
            'full_name',
            'institution',
            'designation',
            'phone',
            'email',
            'region',
        ]

        for field_name in placeholder_fields:
            self.fields[field_name].initial = ''
            self.fields[field_name].widget.attrs['placeholder'] = (
                'Enter ' + self.fields[field_name].label
            )

    def clean(self):
        cleaned_data = super().clean()
        title = cleaned_data.get('title')
        other_title = cleaned_data.get('other_title')

        if title == 'Other' and not other_title:
            self.add_error('other_title', 'Please specify the other title.')

        return cleaned_data