from flask import Flask, render_template, request, redirect, flash, session, url_for, jsonify
import model
import crud
from datetime import datetime, date
import cloudinary.uploader
from cloudinary import CloudinaryImage
from authlib.integrations.flask_client import OAuth
from urllib.parse import quote_plus, urlencode
import json
import os
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
import requests
import random


app = Flask(__name__)
app.secret_key=os.environ['APP_SECRET_KEY']
app.url_map.strict_slashes = False

#Auth0 Configs
oauth=OAuth(app)
oauth.register(
    "auth0",
    client_id = os.environ['AUTH0_CLIENT_ID'],
    client_secret=os.environ['AUTH0_CLIENT_SECRET'],
    client_kwargs={
        "scope": "openid profile email",
    },
    server_metadata_url=f'https://{os.environ["AUTH0_DOMAIN"]}/.well-known/openid-configuration'
)
NEW_USER_MANAGEMENT_TOKEN = ""

# Cloudinary Configs
CLOUDINARY_KEY = os.environ['API_KEY']
CLOUDINARY_SECRET = os.environ['API_SECRET']
CLOUD_NAME = os.environ['CLOUD_NAME']
CLOUDINARY_URL= os.environ['CLOUDINARY_URL']



@app.route('/')
def homepage():
    return render_template("homepage.html")

@app.route('/login')
def login_or_register():
    return oauth.auth0.authorize_redirect(
        redirect_uri=url_for("callback", _external=True)
    )

@app.route('/callback', methods=["GET", "POST"])
def callback():
    token = oauth.auth0.authorize_access_token()
    session['user'] = token
    email = token['userinfo']['email']
    new_user = crud.get_user_by_email(email)
   
    if new_user == None:
        try:
            fname = token['userinfo']['given_name']
            lname = token['userinfo']['family_name']
            new_user = model.User(fname=fname, lname=lname, email=email)
        except:
            fname = token['userinfo']['nickname']
            lname = "Last Name"
            new_user = model.User(fname=fname, lname=lname, email=email)
        
        model.db.session.add(new_user)
        model.db.session.commit()

    return redirect('/user_profile')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(
        "https://" + os.environ["AUTH0_DOMAIN"]
        + "/v2/logout?"
        + urlencode(
            {
                "returnTo": url_for("homepage", _external=True),
                "client_id": os.environ["AUTH0_CLIENT_ID"],
            },
            quote_via=quote_plus,
        )
    )


@app.route('/createUser', methods=['POST'])
def create_user():

    email = request.form.get('email').strip()
    fname = request.form.get('fname').strip()
    lname = request.form.get('lname').strip()
    role = request.form.get('role').strip()

    user = crud.create_user(fname, lname, email)
    model.db.session.add(user)
    model.db.session.commit()


    add_to_cast = crud.add_to_cast(role, admin=False)
    add_to_cast.show_id = (crud.get_show_by_id(session['show_id']).show_id)
    add_to_cast.user_id = user.user_id
    model.db.session.add(add_to_cast)
    model.db.session.commit()

    message = Mail(
        from_email='playbuildpro@gmail.com',
        to_emails=email,
        subject = f'Welcome to {crud.get_show_by_id(session["show_id"]).title}!',
        html_content=f'<strong>Break a leg {fname} {lname}!</strong> <p>Please register to <a href="http://35.86.170.99/">PlayBuild Pro</a>\
            with {email}  to access your show account and upload your Playbill Bio and Headshot for <i>{crud.get_show_by_id(session["show_id"]).title}</i> at {crud.get_show_by_id(session["show_id"]).company.name}! You can edit this information at anytime\
                during the run of your show and, once approved, see those changes rendered to the virtual Playbill!</p>'
    )
    try:
        sg = SendGridAPIClient(os.environ.get('SENDGRID_API_KEY'))
        response = sg.send(message)
    except:
        None
  

    return redirect('/invitecompany')

@app.route('/search', methods=["POST"])
def search_show():

    title = request.form.get("show_title")
    shows = crud.search_shows(title.title())

    if not shows:
        flash("No show by that title! Search again.")
        return redirect('/')

    return render_template("homepage.html", shows=shows)


@app.route('/register_show')
def register_show_form():

    if session.get('user') == None:
        flash('Please Login!')
        return redirect('/')
   
    return render_template("register_show.html")


@app.route('/register_show', methods=["POST"])
def register_show():
    """A route to register a new show"""

    """Get Company Information from Form"""
    company_name = request.form.get('company').strip()
    city = request.form.get('city').strip()
    state = request.form.get('state').strip()
    zip_code = request.form.get('zipcode').strip()
  
    """Get Show Information from Form"""
    title = request.form.get('title').strip()
    theater_name = request.form.get('theater').strip()
    opening_night = request.form.get('openingNight')
    closing_night = request.form.get('closingNight')
    
    """Check if Company is already registered in DB"""
    company_exists = crud.get_company_by_name_city_state(company_name, city, state)
    
    if not company_exists:
        company_exists = crud.register_new_company(company_name, city, state, zip_code)
        model.db.session.add(company_exists)
        model.db.session.commit()
    
    for show in company_exists.shows:
            if show.title == title and show.opening_night == opening_night:   
                flash(f'This show is already registered with {company_exists.name}!')
                return render_template("register_show.html")
               

    new_show = crud.register_new_show(title, opening_night, closing_night, theater_name)
    new_show.company_id = company_exists.company_id
    model.db.session.add(new_show)
    
    model.db.session.commit()

    """Get Playbill Cover Photo"""
    image = request.files['image']
    
    image = cloudinary.uploader.upload(image,
                                            api_key=CLOUDINARY_KEY,
                                            api_secret=CLOUDINARY_SECRET,
                                            cloud_name=CLOUD_NAME,
                                            eager = [
                                                    {"width": 528, 
                                                    "height": 588,
                                                    "crop": "scale"}])
       
    img_url = image['eager'][0]['url']
    update = crud.update_show_image(new_show.show_id, img_url)

    admin = crud.get_user_by_email(session['user']['userinfo']['email'])

    add_admin_to_show = crud.add_to_cast('Admin', True)

    add_admin_to_show.show_id = new_show.show_id

    add_admin_to_show.user_id = admin.user_id
    model.db.session.add(add_admin_to_show)
    model.db.session.commit()

    session['show_id'] = new_show.show_id
    
    return render_template("update_show.html", show={new_show})


@app.route('/api/showInfo')
def get_show_info():

    show = crud.get_show_by_id(session['show_id'])
 
    opening = show.opening_night.strftime("%b %d, '%y")
    closing = show.closing_night.strftime("%b %d, '%y")

    return jsonify({"show": {
        "title": show.title,
        "company": show.company.name,
        "opening_night": opening,
        "closing_night": closing,
        "image": show.image,
        "active": show.active,
        "theater_name": show.theater_name,
        "show_id": show.show_id,
        "city": show.company.city}

    })

@app.route('/updateShowInfo', methods=["POST"])
def edit_show_info():
    
    show = crud.get_show_by_id(session['show_id'])
    title = request.json.get('title')
    company = request.json.get('company')
    opening_night = request.json.get('opening_night')
    closing_night = request.json.get('closing_night')
  


    if show.title != title:
        show.title = title
    if show.company.name != company:
        show.company.name = company
    if show.opening_night != opening_night:
        show.opening_night = opening_night
    if show.closing_night != closing_night:
        show.closing_night = closing_night
   

    model.db.session.commit()

    return jsonify({
        "success": True
    })


@app.route('/api/userinfo')
def get_user_info():
    user = crud.get_user_by_email(session['user']['userinfo']['email'])
    
    return jsonify({"user": {
                "fname": user.fname,
                "lname": user.lname,
                "email": user.email}})


@app.route('/api/usershowinfo')
def get_user_show_info():
    """Return user information from database"""
    user = crud.get_user_by_email(session['user']['userinfo']['email'])
    
    show = crud.get_show_by_id(session['show_id'])
    
    headshot = crud.get_user_headshot_for_show(user, show)

    bio = crud.get_user_bio_for_show(user,show)

    role = crud.get_role(show, user)

    is_admin = crud.is_admin(session['show_id'], user)

    submissions = crud.new_submissions(show)

    if is_admin:
        return jsonify ({"user" : {
                "fname": user.fname,
                "lname": user.lname,
                "email": user.email,
                "role": role,
                "admin": is_admin,
                "submissions": submissions,
                "show_id": show.show_id,
                "show": show.title,
               

    }})


    if headshot != None:
        headshot = headshot.img
       
    else:
        headshot = "/static/img/download.png"

  
    if bio != None:
        bio = bio.bio

    else:
        bio = crud.add_bio("No Bio")
        model.db.session.add(bio)
        bio.show_id = session['show_id']
        bio.user_id = user.user_id
        model.db.session.commit()
        bio = crud.get_user_bio_for_show(user,show)
        bio = bio.bio
       
    
    role = crud.get_role(show, user)
 
    return jsonify ({"user" : {
                "fname": f"{user.fname}",
                "lname": f"{user.lname}",
                "email": f"{user.email}",
                "headshot": headshot,
                "bio": bio,
                "role": role,
                "admin": is_admin,
                "submissions": submissions,
                "show_id": show.show_id

    }})

@app.route('/updateuser', methods=["POST"])
def update_user_info():
    """Update User first name and last name to DB."""
    
    user = crud.get_user_by_email(session['user']['userinfo']['email'])

    fname = request.json.get('fname')
    lname = request.json.get('lname')

    if user.fname != fname:
        user.fname = fname

    if user.lname != lname:
        user.lname = lname

    model.db.session.commit()
    
    return {
        "success": True,
    }


@app.route('/api/usershows')
def get_user_shows():

    user = crud.get_user_by_email(session['user']['userinfo']['email'])

    shows = []

    for show in user.cast:
        submissions = crud.new_submissions(crud.get_show_by_id(show.show_id))
        waiting_on_submits = crud.waiting_on_submissions(crud.get_show_by_id(show.show_id))
        headshot = crud.get_user_headshot_for_show(user, show.shows)

        if headshot:
            headshot = headshot.img
        else:
            headshot = "/static/img/download.png"

        bio = crud.get_user_bio_for_show(user, show.shows)
        if bio:
            bio = bio.bio
        else:
            bio = "No Bio Submitted"
        
        shows.append({
            "show_id": show.show_id,
            "title": show.shows.title,
            "role": show.role,
            "is_admin": show.admin,
            "active": show.shows.active,
            "image": show.shows.image,
            "submissions": submissions,
            "waiting": waiting_on_submits,
            "headshot": headshot,
            "bio": bio
        })

    return jsonify({'shows': shows})

@app.route('/user_profile')
def user_profile():
    """A route to a user's profile"""

    # Check that a session has been created from
    # login or register user routes
    if session.get('user') == None:
        flash('Please Login!')
        return redirect('/')

    user_email = session['user']['userinfo']['email']
    # user_id = session['user']

    #Grab user from DB by querying PK with user_id arguement
    user = crud.get_user_by_email(session['user']['userinfo']['email'])
    

    #check that the logged in user matches the profile we are visiting
    if user == None or user.email != user_email:

        flash('Oops, something went wrong here')
        return redirect('/')

    
    return render_template("user_profile.html", user=user)

@app.route('/updateshow')
def update_show():
    show_id = request.args.get('show_id')

    if show_id == None:
        show_id = session['show_id']

    show = crud.get_show_by_id(show_id)
    user = crud.get_user_by_email(session['user']['userinfo']['email'])
    is_admin = crud.is_admin(show_id, user)

    headshot = crud.get_user_headshot_for_show(user, show)
    bio = crud.get_user_bio_for_show(user,show)
    role = crud.get_role(show, user)
    new_submissions = crud.new_submissions(show)
    

    session['show_id'] = show_id
    
    return render_template("update_show.html", show=show)


@app.route('/invitecompany')
def cast():
    
  
    if session.get('user') == None:
        flash('Please Login!')
        return redirect('/')

    user = crud.get_user_by_email(session['user']['userinfo']['email'])
    if not crud.is_admin(session['show_id'], user):
        flash('You are not an admin for this show. Please update your headshot and bio from your profile.')
        return redirect(f'/user_profile')
    
    cast = crud.get_cast_by_show_id(session['show_id'])
    show = crud.get_show_by_id(session['show_id'])

    return render_template("invitecompany.html")
    
@app.route('/approveheadshot', methods=["POST"])
def approve_headshot():

    user_id = request.form.get('user_id')
    user = model.User.query.get(user_id)
    show = crud.get_show_by_id(session['show_id'])
    headshot = crud.get_user_headshot_for_show(user,show)

    approval = crud.approve_headshot_to_publish(headshot.headshot_id)
    
    return redirect('/approvesubmits')


@app.route('/approvebio', methods=["POST"])
def approve_bio():

    user_id = request.form.get('user_id')
    user = model.User.query.get(user_id)
    show = crud.get_show_by_id(session['show_id'])
    bio = crud.get_user_bio_for_show(user, show)

    approval = crud.approve_bio_to_publish(bio.bio_id)

    return redirect('approvesubmits')


@app.route('/addcast', methods=["POST"])
def add_cast():

    show = crud.get_show_by_id(session['show_id'])
    cast = crud.get_cast_by_show_id(show.show_id)
    user = crud.get_user_by_email(request.form.get("email"))
    role = request.form.get("role")
   
    if user == None:
        return redirect('/createUser', code=307)

    already_added = crud.check_for_user_in_show(user, show.show_id)
    
    if already_added:
        flash("You have already added this user to your show. If you do not see your user in this list, please check with the user that they have registered with PlayBuild Pro!")
        return redirect('/invitecompany')

    if user:
        new_cast = crud.add_to_cast(role, False)
        new_cast.show_id = show.show_id
        new_cast.user_id = user.user_id
        model.db.session.add(new_cast)
        model.db.session.commit()
        message = Mail(
        from_email='playbuildpro@gmail.com',
        to_emails= user.email,
        subject = f'Welcome to {show.title}!',
        html_content=f'<strong>Break a leg {user.fname} {user.lname}!</strong> <p>Please login to <a href="https://www.playbuildpro.com">PlayBuild Pro</a>\
            to access your show account and upload your Playbill Bio and Headshot for <i>{show.title}</i> at {show.company.name}! You can edit this information at anytime\
                during the run of your show and, once approved, see those changes rendered to the live playbill!</p>'
    )
    try:
        sg = SendGridAPIClient(os.environ.get('SENDGRID_API_KEY'))
        response = sg.send(message)
    except:
        None
  
   
    return redirect('/invitecompany')


@app.route('/update_actor', methods=["POST"])
def udpate_actor():

    user_id = request.json.get("id")
    new_role = request.json.get("role")
    
    crud.update_actor(user_id, new_role, session['show_id'])

    return jsonify({"message": "success"})


@app.route('/approvesubmits')
def approval():
    return render_template("whoswhoapproval.html")


@app.route('/update_headshot', methods=["POST"])
def update_headshot():

    new_headshot = request.files['headshot']
    user = crud.get_user_by_email(session['user']['userinfo']['email'])
    show = crud.get_show_by_id(session['show_id'])
    current_headshot = crud.get_user_headshot_for_show(user, show)

    update_headshot = crud.update_headshot(current_headshot, new_headshot, user, show)



    return redirect(f'/updateshow')



@app.route('/update_bio', methods=["POST"])
def update_bio():

    user = crud.get_user_by_email(session['user']['userinfo']['email'])
    show= crud.get_show_by_id(session['show_id'])

    bio = crud.get_user_bio_for_show(user,show)
   
    update = request.form.get('update')


    update_bio = crud.update_bio(bio, update)

    update_bio.user_id = user.user_id
    update_bio.show_id = show.show_id
    model.db.session.commit()

  
    return redirect(f'/updateshow')



@app.route('/viewplaybill')
def viewplaybill():

    show_id = request.args.get('show_id')
   
    if not show_id:
        show_id = session['show_id']

    session['show_id'] = show_id
    show = crud.get_show_by_id(show_id)

    if show == None:
        flash('Oops, something went wrong here!')
        return redirect('/')
        
    return render_template('playbill.html')
    

@app.route('/editplaybillimage', methods=["POST"])
def edit_playbill():
    show = crud.get_show_by_id(session['show_id'])

    image = request.files['image']
    
    image = cloudinary.uploader.upload(image,
                                            api_key=CLOUDINARY_KEY,
                                            api_secret=CLOUDINARY_SECRET,
                                            cloud_name=CLOUD_NAME,
                                            eager = [
                                                    {"width": 528, 
                                                    "height": 588,
                                                    "crop": "scale"}])
       
    img_url = image['eager'][0]['url']
    update = crud.update_show_image(show.show_id, img_url)

    return redirect(f'/updateshow')

@app.route('/api/inviteCast')
def current_cast():

    company = []

    current_cast = crud.get_cast_by_show_id(session['show_id'])

    for member in current_cast:
        company.append({
            'fname': member.user.fname,
            'lname': member.user.lname,
            'role': member.role,
            'id': member.user.user_id
            })
   

    return jsonify({'company': company})

@app.route('/api/getCast')
def get_cast_list():

    cast = crud.get_cast_by_show_id(session['show_id'])

    show = crud.get_show_by_id(session['show_id'])
    
    castList = []

    pendingApproval = []
   
    for member in cast:
    
        headshot = crud.get_user_headshot_for_show(member.user, show)
        bio = crud.get_user_bio_for_show(member.user, show)
       
        if headshot == None:
            headshot = crud.add_new_headshot("/static/img/download.png")
            model.db.session.add(headshot)
            headshot.show_id = show.show_id
            headshot.user_id = member.user_id
            headshot.pending = True
            model.db.session.commit()

            headshot = crud.get_user_headshot_for_show(member.user, show)
            hpend = headshot.pending

        if bio == None:
           
            new_bio = crud.add_bio('No Bio Submitted')
            model.db.session.add(new_bio)
            new_bio.show_id = show.show_id
            new_bio.user_id = member.user_id
            new_bio.pending = True
            model.db.session.commit()

        bio = crud.get_user_bio_for_show(member.user, show)
       
       
        
        if member.role == "Admin":
            continue

        if (headshot.pending == False and bio.pending == False):
            castList.append({
                "fname": member.user.fname,
                "lname": member.user.lname,
                "role": member.role,
                "headshot": headshot.img,
                "hpend": headshot.pending,
                "bio" : bio.bio,
                "bpend": bio.pending,
                "id" : member.user.user_id
            })
        else:
            pendingApproval.append({
                "fname": member.user.fname,
                "lname": member.user.lname,
                "role": member.role,
                "headshot": headshot.img,
                "hpend": headshot.pending,
                "bio" : bio.bio,
                "bpend": bio.pending,
                "id" : member.user.user_id
            })

   
    return jsonify({
                    'cast' : castList, 
                    'pending': pendingApproval})

@app.route('/api/allShows')
def all_shows():

    showsInfo = []
    shows = model.Show.query.all()

    for show in shows:
        showsInfo.append({
            "title": show.title,
            "image": show.image,
            "theater_name": show.theater_name,
            "company": show.company.name,
            "city": show.company.city,
            "id": show.show_id
        })
    return jsonify({'shows': showsInfo})

@app.route('/archive', methods=["POST"])
def archive():

    show_id = request.json.get('show')

    if not show_id:
        show_id = session['show_id']

    crud.archive_show(show_id)

    return redirect('/user_profile')


@app.route('/delete_from_cast', methods=["POST"])
def delete_from_cast():

    user_id = request.form.get('id')
    crud.remove_from_cast(user_id, session['show_id'])

    return redirect('/invitecompany')


if __name__ == "__main__":
    model.connect_to_db(app)
    app.run()