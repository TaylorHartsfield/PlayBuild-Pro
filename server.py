from flask import Flask, render_template, request, redirect, flash, session, url_for, jsonify
import model
import crud
from datetime import datetime, date
import cloudinary.uploader
from cloudinary import CloudinaryImage
from authlib.integrations.flask_client import OAuth
from urllib.parse import quote_plus, urlencode
import http.client
import json
import os
import requests


app = Flask(__name__)
app.secret_key=os.environ['APP_SECRET_KEY']

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

    flash(f'Break a leg, {new_user.fname} ')
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


# @app.route('/register_user', methods=["POST"])
# def register_user():
#     """Route to register a new user"""

#     #Use value of email input to query DB for existing user
#     email = request.form.get("email")
#     user_exists = model.User.query.filter_by(email=email).first()

#     #Redirect user to login page if they are already a registered user
#     if user_exists != None:
#         flash("You are already registered. Please login.")
#         return redirect('/login')

#     #Create new user entry from remaining form values
#     fname = request.form.get("fname")
#     lname = request.form.get("lname")

#     new_user = model.User(fname=fname, lname=lname, email=email)
#     #call hash_password method to hash password before commiting to DB
#     new_user.hash_password(request.form.get("password"))

#     #add and commit new user to the DB
#     model.db.session.add(new_user)
#     model.db.session.commit()
    
#     #create session for user
#     session['user'] = new_user.user_id

#     #Redirect user to their profile page
#     flash(f'Break a leg, {fname}!', category='success')
#     return redirect(f'/user_profile')

@app.route('/search', methods=["POST"])
def search_show():

    title = request.form.get("show_title")
    shows = crud.search_shows(title)

    if not shows:
        flash("No show by that title! Search again.")
        return redirect('/')

    return render_template("homepage.html", shows=shows)


@app.route('/register_show')
def register_show_form():

    if not session:
        flash("Please login to register a show!")
        return redirect('/login')
   
    return render_template("register_show.html")


@app.route('/register_show', methods=["POST"])
def register_show():
    """A route to register a new show"""

    """Get Company Information from Form"""
    company_name = request.json.get('company')
    city = request.json.get('city')
    state = request.json.get('state')
    zip_code = request.json.get('zipcode')
  
    """Get Show Information from Form"""
    title = request.json.get('title')
    theater_name = request.json.get('theater')
    opening_night = date.fromisoformat(request.json.get('openingNight'))
    closing_night = date.fromisoformat(request.json.get('closingNight'))
    
    """Check if Company is already registered in DB"""
    company_exists = crud.get_company_by_name_city_state(company_name, city, state)
    
    if not company_exists:
        company_exists = crud.register_new_company(company_name, city, state, zip_code, website=None,logo=None)
        model.db.session.add(company_exists)
        model.db.session.commit()
    
    for show in company_exists.shows:
            if show.title == title and show.opening_night == opening_night:   
                flash(f'This show is already registered with {company_exists.name}!')
                return render_template("register_show.html")
                # jsonify({
                    # "message": f"This show is already registered with {company_exists.name}",
                    # "url":"/registershow"})

    new_show = crud.register_new_show(title, opening_night, closing_night, theater_name)
    new_show.company_id = company_exists.company_id
    model.db.session.add(new_show)
    
    model.db.session.commit()

    admin = crud.get_user_by_email(session['user']['userinfo']['email'])

    add_admin_to_show = crud.add_to_cast('Admin', True)

    add_admin_to_show.show_id = new_show.show_id

    add_admin_to_show.user_id = admin.user_id
    model.db.session.add(add_admin_to_show)
    model.db.session.commit()

    session['show_id'] = new_show.show_id
    flash('Show registered!')
    return render_template("add_cast.html")
    
    # jsonify({
        # "message": "Show Registered!",
        # "url": '/invitecompany'})
    

@app.route('/api/showInfo')
def get_show_info():

    show = crud.get_show_by_id(session['show_id'])

    return jsonify({"show": {
        "title": show.title,
        "company": show.company.name,
        "opening_night": show.opening_night,
        "closing_night": show.closing_night,
        "image": show.image,
        "active": show.active,
        "tickets": show.tickets,
        "theater_name": show.theater_name,
        "show_id": show.show_id}

    })

@app.route('/updateShowInfo', methods=["POST"])
def edit_show_info():
    
    show = crud.get_show_by_id(session['show_id'])
    title = request.json.get('title')
    company = request.json.get('company')
    opening_night = request.json.get('opening_night')
    closing_night = request.json.get('closing_night')
    tickets = request.json.get('tickets')


    if show.title != title:
        show.title = title
    if show.company.name != company:
        show.company.name = company
    if show.opening_night != opening_night:
        show.opening_night = opening_night
    if show.closing_night != closing_night:
        show.closing_night = closing_night
    if show.tickets != tickets:
        show.tickets = tickets

    model.db.session.commit()

    return jsonify({
        "success": True
    })


@app.route('/api/userinfo')
def get_user_info():
    user = crud.get_user_by_email(session['user']['userinfo']['email'])
    
    return jsonify({"user": {
                "fname": f"{user.fname}",
                "lname": f"{user.lname}",
                "email": f"{user.email}"}})


@app.route('/api/usershowinfo')
def get_user_show_info():
    """Return user information from database"""
    user = crud.get_user_by_email(session['user']['userinfo']['email'])
    
    show = crud.get_show_by_id(session['show_id'])
    
    headshot = crud.get_user_headshot_for_show(user, show)
    is_admin = crud.is_admin(session['show_id'], user)
    submissions = crud.new_submissions(show)
   
    if headshot != None:
        headshot = headshot.img
       
    else:
        headshot = "/static/img/download.png"
    

    bio = crud.get_user_bio_for_show(user,show)
    print(bio,'************HERE IS BIUO!!!!')
    if bio != None:
        bio = bio.bio

    else:
        bio = crud.add_bio("No Bio")
        model.db.session.add(bio)
        bio.show_id = session['show_id']
        bio.user_id = user.user_id
        model.db.session.commit()
        bio = crud.get_user_bio_for_show(user,session['show_id'])
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
        shows.append({
            "show_id": show.show_id,
            "title": show.shows.title,
            "role": show.role,
            "is_admin": show.admin,
            "active": show.shows.active
        })

    return jsonify({'shows': shows})

@app.route('/user_profile')
def user_profile():
    """A route to a user's profile"""

    # Check that a session has been created from
    # login or register user routes
    if not session:
        flash('Please Login')
        return redirect('/login')

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
    
    return render_template("update_show.html", show=show, admin=is_admin, 
                                               user=user, headshot=headshot, 
                                               bio=bio, role=role,
                                               new_submissions=new_submissions)


@app.route('/invitecompany')
def cast():
    
    if not session['user']:
        flash('Please Login')
        return redirect('/login')

    user = crud.get_user_by_email(session['user']['userinfo']['email'])
    if not crud.is_admin(session['show_id'], user):
        flash('You are not an admin for this show. Please update your headshot and bio from your profile.')
        return redirect(f'/user_profile')
    
    cast = crud.get_cast_by_show_id(session['show_id'])
    show = crud.get_show_by_id(session['show_id'])

    return render_template("add_cast.html", show=show, cast=cast)
    
@app.route('/approveheadshot', methods=["POST"])
def approve_submissions():

    user_id = request.form.get('user_id')
    print(user_id, '************USERID!')
    user = model.User.query.get(user_id)
    show = crud.get_show_by_id(session['show_id'])
    headshot = crud.get_user_headshot_for_show(user,show)

    approval = crud.approve_headshot_to_publish(headshot.headshot_id)
    
    return redirect('/approvesubmits')


@app.route('/addcast/<show_id>', methods=["POST"])
def add_cast(show_id):

    cast = crud.get_cast_by_show_id(show_id)
    show = crud.get_show_by_id(show_id)
    user = crud.get_user_by_email(request.form.get("email"))
    role = request.form.get("role")
    admin = request.form.get("admin")

    if admin != None:
        admin = True

    if user == None:
        flash("User does not exist with PlayBuild Pro! Invite them to register")
        return redirect(f'/invitecompany')


    already_added = crud.check_for_user_in_show(user, show_id)
    
    if already_added:
        flash("You have already added this user to your show. If you do not see your user in this list, please check with the user that they have registered with PlaybillRender")
        return redirect(f'/invitecompany')

    if user:
        new_cast = crud.add_to_cast(role, admin)
        new_cast.show_id = show.show_id
        new_cast.user_id = user.user_id
        model.db.session.add(new_cast)
        model.db.session.commit()
        flash(f'{user.fname}, added to cast!')
        return redirect(f'/invitecompany')


@app.route('/update_actor', methods=["POST"])
def udpate_actor():

    user_id = request.json["user_id"]
    updated_role = request.json["updated_role"]

    if crud.update_actor(user_id, updated_role):
   
        return "Success"


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


    flash("Headshot Updated!")
    return redirect(f'/updateshow')


@app.route('/deny_headshot', methods=["POST"])
def deny_headshot():


    headshot_id = request.form.get('headshot_id')
    headshot = model.Headshot.query.get(headshot_id)
    show_id = headshot.show_id
    model.db.session.commit()

    flash(f'Headshot not published. Sent back to {headshot.user.fname}{headshot.user.lname} for updating.')
    return redirect(f'/approvesumbits')



@app.route('/update_bio', methods=["POST"])
def update_bio():

    user = crud.get_user_by_email(session['user']['userinfo']['email'])
    show= crud.get_show_by_id(session['show_id'])
    bio = crud.get_user_bio_for_show(user,show)
    update = request.form.get('update')
   

    update_bio = crud.update_bio(bio, update)
    bio.user_id = user.user_id
    bio.show_id = show.show_id
    model.db.session.commit()

    flash('Your Bio has been updated!')
    return redirect(f'/updateshow')


@app.route('/approve_bio', methods=["POST"])
def approve_bio():

    bio_id = request.form.get('bio_id')
    approved_bio = crud.approve_bio_to_publish(bio_id)

    return redirect(f'/approvesubmits')

@app.route('/deny_bio', methods=["POST"])
def deny_bio():

    bio_id = request.form.get('bio_id')
    bio = model.Bio.query.get(bio_id)
    show_id = bio.show_id
    bio.show_id = None
    model.db.session.commit()

    flash(f'Headshot not published. Sent back to {bio.user.fname}{bio.user.lname} for updating.')
    return redirect(f'/viewheadshots/{show_id}')


@app.route('/viewplaybill/')
def viewplaybill():

    show_id = request.args.get('show_id')
    
    if not show_id:
        show_id = session['show_id']
       

    session['show_id'] = show_id
    show = crud.get_show_by_id(show_id)

    
    if show==None:
        flash('Oops, something went wrong here!')
        return redirect('/')
   
    return render_template('playbillbase.html', show=show)

@app.route('/editPlaybill')
def editing_playbill():

    show = crud.get_show_by_id(session['show_id'])

    flash('Editing Playbill Here!')
    return redirect(f'/updateshow')

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
    
@app.route('/castlist')
def playbill_castlist():

    cast = crud.get_cast_by_show_id(session['show_id'])
    print(session['show_id'], 'SESSION FOR CASTLIST!!!!!!!!!!!!!!!!!!!!!!!')
    show = crud.get_show_by_id(session['show_id'])
    if show==None:
        flash('Oops, something went wrong here!')
        return redirect('/')
   

    return render_template("castlist.html", show=show, cast=cast)

@app.route('/whoswho')
def playbill_headshots():

    show = crud.get_show_by_id(session['show_id'])
    cast = crud.get_cast_by_show_id(session['show_id'])
    
    if show==None:
        flash('Oops, something went wrong here!')
        return redirect('/')
    
    return render_template('whoswho.html', show=show, cast=cast)


@app.route('/api/getCast')
def get_cast_list():

    cast = crud.get_cast_by_show_id(session['show_id'])
    show = crud.get_show_by_id(session['show_id'])
    castList = []
    pendingApproval = []


    for member in cast:
    
        headshot = member.user.headshots
        for headshots in headshot:
            # if len(headshot) == 0:
            #     headshot="/static/img/download.png"
            if headshots.show_id == show.show_id:
                headshot = headshots.img
                hpend = headshots.pending
  
        if headshot == []:
            headshot = "/static/img/download.png"
            hpend = False

        bio = crud.get_user_bio_for_show(member.user, show)

        if bio == None:
            bio = 'No Bio Submitted'
            bpend = False
        else:
            bpend = bio.pending
            bio = bio.bio
           
        if member.role == "Admin":
            continue

        if (hpend == False and bpend == False):
            castList.append({
                "fname": member.user.fname,
                "lname": member.user.lname,
                "role": member.role,
                "headshot": headshot,
                "hpend": hpend,
                "bio" : bio,
                "bpend": bpend,
                "id" : member.user.user_id
            })
        else:
            pendingApproval.append({
                "fname": member.user.fname,
                "lname": member.user.lname,
                "role": member.role,
                "headshot": headshot,
                "hpend": hpend,
                "bio" : bio,
                "bpend": bpend,
                "id" : member.user.user_id
            })

    return jsonify({
                    'cast' : castList, 
                    'pending': pendingApproval})



if __name__ == "__main__":
    model.connect_to_db(app)
    app.run(host='0.0.0.0', debug=True)